"""Adaptadores de AWS para orquestación y eventos.

Límites reales de Step Functions Standard que este adaptador respeta:

- Duración máxima **1 año** (no "sin límite").
- Historial retenido **90 días** tras el cierre de la ejecución.
- **25.000 eventos** de historial por ejecución.
- Payload de **256 KiB**.

El puerto no expone `waitForTaskToken` ni `SendTaskSuccess`: habla de
`await_manual_decision` y `resume`. Aquí se traduce a la primitiva de AWS, que
sí admite hasta un año de espera con tokens ilimitados y `SendTaskHeartbeat`.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ...config import Settings
from ...domain.value_objects import SessionId, TenantId, utc_now
from ...errors import ProviderUnavailableError
from ...ports.events_bus import EventBusPort, IntegrationEvent
from ...ports.saga import OnboardingSagaPort, ResumeToken, SagaHandle, SagaStatus
from ._client import client

#: Cuotas reales de Step Functions Standard.
MAX_EXECUTION_SECONDS: int = 31_536_000  # 1 año
HISTORY_RETENTION_DAYS: int = 90
MAX_HISTORY_EVENTS: int = 25_000
MAX_PAYLOAD_BYTES: int = 262_144


class StepFunctionsSaga(OnboardingSagaPort):
    """Saga sobre Step Functions con el patrón anidado padre/hijo.

    El padre es Standard (exactly-once y esperas largas); los pasos
    automatizados, idempotentes y cortos van a workflows hijos Express, que
    cobran por duración en vez de por transición. El ahorro es **específico
    de cada flujo**: sobre un flujo ejemplo ejecutado 1.000 veces, Standard
    puro con 17 transiciones cuesta 0,42 USD, Express puro con 11.300 ms de
    media cuesta 0,01 USD (98 % menos) y el anidado con padre de 8
    transiciones cuesta 0,20 USD (~52 %). Arrancar un workflow anidado no
    tiene coste adicional.
    """

    __slots__ = ("_settings", "_state_machine_arn")

    def __init__(self, settings: Settings, state_machine_arn: str = "") -> None:
        self._settings = settings
        self._state_machine_arn = state_machine_arn or (
            f"arn:aws:states:{settings.region}:000000000000:stateMachine:"
            f"{settings.resource_name('onboarding')}"
        )

    def start_verification(
        self,
        tenant_id: TenantId,
        session_id: SessionId,
        *,
        plan: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> SagaHandle:
        import json  # noqa: PLC0415

        payload = {
            "tenant_id": tenant_id.value,
            "session_id": session_id.value,
            # Solo punteros: el payload está limitado a 256 KiB.
            "artifact_refs": dict(context or {}).get("artifact_refs", {}),
            "plan_hash": plan.get("content_hash", ""),
        }
        encoded = json.dumps(payload)
        if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ProviderUnavailableError(
                "el payload inicial supera los 256 KiB de Step Functions",
                provider_id="stepfunctions",
            )
        try:
            response = client("stepfunctions", self._settings.region).start_execution(
                stateMachineArn=self._state_machine_arn,
                # El nombre de ejecución es la clave de idempotencia natural:
                # reintentar con el mismo nombre no arranca una segunda.
                name=f"{tenant_id.value}-{session_id.value}",
                input=encoded,
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError(
                "Step Functions no respondió", provider_id="stepfunctions"
            ) from exc
        return SagaHandle(
            execution_id=str(response["executionArn"]),
            tenant_id=tenant_id.value,
            session_id=session_id.value,
            started_at=utc_now().isoformat(),
            orchestrator="stepfunctions",
        )

    def await_manual_decision(
        self, handle: SagaHandle, *, reason: str, ttl_seconds: int = 604_800
    ) -> ResumeToken:
        raise NotImplementedError(
            "El task token de `.waitForTaskToken` lo genera el propio estado en ejecución y llega "
            "al worker por el payload; no se puede solicitar desde fuera. Falta decidir dónde se "
            "persiste ese token para que el caso de uso de revisión lo recupere: en el ítem de la "
            "sesión (simple, pero un token es material sensible que quedaría junto al expediente) "
            "o en una tabla aparte con TTL y política IAM propia."
        )

    def resume(self, token: ResumeToken, payload: Mapping[str, Any]) -> SagaHandle:
        import json  # noqa: PLC0415

        client("stepfunctions", self._settings.region).send_task_success(
            taskToken=token.value, output=json.dumps(dict(payload))
        )
        return SagaHandle(
            execution_id=token.value,
            tenant_id=token.tenant_id,
            session_id=token.session_id,
            started_at=utc_now().isoformat(),
            orchestrator="stepfunctions",
        )

    def status(self, handle: SagaHandle) -> SagaStatus:
        response = client("stepfunctions", self._settings.region).describe_execution(
            executionArn=handle.execution_id
        )
        return SagaStatus(
            execution_id=handle.execution_id,
            state=str(response.get("status", "UNKNOWN")),
            current_step=None,
            suspended=str(response.get("status")) == "RUNNING",
            context={},
        )

    def compensate(self, handle: SagaHandle, *, reason: str) -> SagaStatus:
        raise NotImplementedError(
            "Falta decidir si las compensaciones se ejecutan como una rama del mismo workflow "
            "(consume eventos de historial del mismo presupuesto de 25.000) o como una ejecución "
            "independiente. La segunda opción es más limpia pero pierde el contexto de la saga "
            "original y obliga a reconstruirlo desde el expediente."
        )

    def abort(self, handle: SagaHandle, *, reason: str) -> SagaStatus:
        client("stepfunctions", self._settings.region).stop_execution(
            executionArn=handle.execution_id, error="OG_ABORTED", cause=reason
        )
        return self.status(handle)


class EventBridgeBus(EventBusPort):
    """Bus de integración sobre EventBridge.

    El `sequence` viaja en el detalle **a propósito**: EventBridge no
    garantiza orden y el consumidor debe reordenar por sesión. Es la misma
    disciplina que exige Firestore + Eventarc en GCP, así que el consumidor
    escrito para una nube sirve para la otra.
    """

    __slots__ = ("_settings", "_bus_name")

    def __init__(self, settings: Settings, bus_name: str = "") -> None:
        self._settings = settings
        self._bus_name = bus_name or settings.resource_name("bus")

    def publish(self, event: IntegrationEvent) -> str:
        return self.publish_batch([event])[0]

    def publish_batch(self, events: Sequence[IntegrationEvent]) -> tuple[str, ...]:
        import json  # noqa: PLC0415

        if not events:
            return ()
        entries = [
            {
                "EventBusName": self._bus_name,
                "Source": "onboarding-generico",
                "DetailType": event.event_type,
                "Detail": json.dumps(
                    {
                        "event_id": event.event_id,
                        "tenant_id": event.tenant_id,
                        "session_id": event.session_id,
                        "sequence": event.sequence,
                        "occurred_at": event.occurred_at,
                        "payload": dict(event.payload),
                    }
                ),
            }
            for event in sorted(events, key=lambda e: e.sequence)
        ]
        response = client("events", self._settings.region).put_events(Entries=entries)
        if response.get("FailedEntryCount", 0):
            raise ProviderUnavailableError(
                "EventBridge rechazó parte del lote",
                provider_id="eventbridge",
                failed=response["FailedEntryCount"],
            )
        return tuple(str(entry["EventId"]) for entry in response.get("Entries", []))

    def published_for(self, tenant_id: TenantId, session_id: str) -> tuple[IntegrationEvent, ...]:
        raise NotImplementedError(
            "EventBridge no permite consultar eventos publicados. El reproceso debe iterar la "
            "colección de auditoría, no el bus. Falta decidir si se archiva el bus con "
            "EventBridge Archive (que sí permite replay, con coste de almacenamiento) o si el "
            "expediente es la única fuente de verdad para la reconstrucción."
        )


__all__ = [
    "HISTORY_RETENTION_DAYS",
    "MAX_EXECUTION_SECONDS",
    "MAX_HISTORY_EVENTS",
    "MAX_PAYLOAD_BYTES",
    "EventBridgeBus",
    "StepFunctionsSaga",
]
