"""Adaptadores de GCP para orquestación y eventos.

Restricciones reales que gobiernan este adaptador:

- **Cloud Workflows**: 512 KB acumulados por ejecución (variables +
  argumentos + eventos) — el límite dominante del diseño; respuesta HTTP
  2 MB; string 256 KB; 100.000 pasos por ejecución; **10 ramas** por paso
  `parallel`; anidamiento paralelo de 2 niveles; 20 iteraciones concurrentes;
  profundidad de call stack 20; código fuente 128 KB; expresión 400
  caracteres; retención de ejecuciones 90 días.
- **Callbacks**: timeout por defecto de 43.200 s (12 h), **un solo slot
  pendiente por endpoint** (el segundo recibe HTTP 429) y **sin heartbeat**.

Por eso `await_manual_decision` **no** genera un `await_callback`: persiste el
estado, termina la ejecución y la reanudación arranca una nueva con
`executions.run`. Es menos elegante y no tiene techo, que es lo que hace falta
cuando un caso escala a compliance o cruza un fin de semana.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from ...config import Settings
from ...domain.value_objects import SessionId, TenantId, utc_now
from ...errors import ProviderUnavailableError
from ...ports.events_bus import EventBusPort, IntegrationEvent
from ...ports.saga import OnboardingSagaPort, ResumeToken, SagaHandle, SagaStatus
from ._client import publisher_client, workflows_executions_client

#: Límites reales de Cloud Workflows.
MAX_EXECUTION_DATA_BYTES: int = 524_288
MAX_PARALLEL_BRANCHES: int = 10
MAX_SOURCE_BYTES: int = 131_072
MAX_EXPRESSION_LENGTH: int = 400
CALLBACK_DEFAULT_TIMEOUT_SECONDS: int = 43_200
EXECUTION_RETENTION_DAYS: int = 90


class CloudWorkflowsSaga(OnboardingSagaPort):
    """Saga sobre Cloud Workflows con el patrón de persistir y relanzar."""

    __slots__ = ("_location", "_settings", "_workflow_name")

    def __init__(
        self, settings: Settings, workflow_name: str = "", location: str = "us-central1"
    ) -> None:
        self._settings = settings
        self._location = location
        self._workflow_name = workflow_name or settings.resource_name("onboarding")

    def _parent(self) -> str:
        return (
            f"projects/{self._settings.gcp_project}/locations/{self._location}"
            f"/workflows/{self._workflow_name}"
        )

    def start_verification(
        self,
        tenant_id: TenantId,
        session_id: SessionId,
        *,
        plan: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> SagaHandle:
        import json

        arguments = {
            "tenant_id": tenant_id.value,
            "session_id": session_id.value,
            # Solo punteros: 512 KB acumulados por ejecución es el límite más
            # restrictivo de todo el diseño.
            "artifact_refs": dict(context or {}).get("artifact_refs", {}),
            "plan_hash": plan.get("content_hash", ""),
        }
        encoded = json.dumps(arguments)
        if len(encoded.encode("utf-8")) > MAX_EXECUTION_DATA_BYTES // 4:
            raise ProviderUnavailableError(
                "los argumentos consumen demasiado del presupuesto de 512 KB por ejecución",
                provider_id="cloudworkflows",
            )
        try:
            execution = workflows_executions_client().create_execution(
                request={"parent": self._parent(), "execution": {"argument": encoded}}
            )
        except Exception as exc:
            raise ProviderUnavailableError(
                "Cloud Workflows no respondió", provider_id="cloudworkflows"
            ) from exc
        return SagaHandle(
            execution_id=str(execution.name),
            tenant_id=tenant_id.value,
            session_id=session_id.value,
            started_at=utc_now().isoformat(),
            orchestrator="cloudworkflows",
        )

    def await_manual_decision(
        self, handle: SagaHandle, *, reason: str, ttl_seconds: int = 604_800
    ) -> ResumeToken:
        """Persiste el estado y **termina** la ejecución.

        No se usa `events.await_callback`: 12 h por defecto, un solo slot
        pendiente por endpoint y sin heartbeat. Un TTL de 7 días no cabe ahí.
        """
        from datetime import timedelta

        token = ResumeToken(
            value=uuid.uuid4().hex,
            session_id=handle.session_id,
            tenant_id=handle.tenant_id,
            expires_at=(utc_now() + timedelta(seconds=ttl_seconds)).isoformat(),
            reason=reason,
        )
        raise NotImplementedError(
            "Falta decidir dónde se persiste el estado congelado de la saga al terminar la "
            f"ejecución para poder relanzarla con executions.run (token {token.value[:8]}...): "
            "en el documento de la sesión (simple, pero mezcla estado de orquestación con "
            "expediente) o en una colección de sagas aparte con su propia política de retención. "
            "La segunda separa responsabilidades pero añade una escritura por suspensión."
        )

    def resume(self, token: ResumeToken, payload: Mapping[str, Any]) -> SagaHandle:
        """Arranca una ejecución nueva con el estado recuperado."""
        import json

        arguments = {
            "tenant_id": token.tenant_id,
            "session_id": token.session_id,
            "resume_token": token.value,
            **dict(payload),
        }
        execution = workflows_executions_client().create_execution(
            request={"parent": self._parent(), "execution": {"argument": json.dumps(arguments)}}
        )
        return SagaHandle(
            execution_id=str(execution.name),
            tenant_id=token.tenant_id,
            session_id=token.session_id,
            started_at=utc_now().isoformat(),
            orchestrator="cloudworkflows",
        )

    def status(self, handle: SagaHandle) -> SagaStatus:
        execution = workflows_executions_client().get_execution(
            request={"name": handle.execution_id}
        )
        state = str(execution.state)
        return SagaStatus(
            execution_id=handle.execution_id,
            state=state,
            current_step=None,
            suspended=state == "ACTIVE",
            context={},
        )

    def compensate(self, handle: SagaHandle, *, reason: str) -> SagaStatus:
        raise NotImplementedError(
            "Cloud Workflows no tiene un mecanismo de compensación integrado equivalente al Catch "
            "de ASL con ramas de compensación. Falta decidir si las compensaciones se modelan como "
            "un workflow aparte invocado por el manejador de error o como una sección del mismo "
            "workflow, sabiendo que el segundo consume del presupuesto de 512 KB."
        )

    def abort(self, handle: SagaHandle, *, reason: str) -> SagaStatus:
        workflows_executions_client().cancel_execution(request={"name": handle.execution_id})
        return self.status(handle)


class PubSubBus(EventBusPort):
    """Bus de integración sobre Pub/Sub con **ordering keys**.

    Firestore + Eventarc no garantiza orden ni permite replay. Las ordering
    keys de Pub/Sub recuperan el orden **por sesión**, que es la granularidad
    que necesita la saga. El replay sigue sin existir: para reprocesar se
    itera la colección, no el stream.
    """

    __slots__ = ("_settings", "_topic")

    def __init__(self, settings: Settings, topic: str = "") -> None:
        self._settings = settings
        self._topic = topic or settings.resource_name("events")

    def _topic_path(self) -> str:
        return f"projects/{self._settings.gcp_project}/topics/{self._topic}"

    def publish(self, event: IntegrationEvent) -> str:
        import json

        future = publisher_client().publish(
            self._topic_path(),
            data=json.dumps(dict(event.payload)).encode("utf-8"),
            # La ordering key agrupa por sesión: es la única forma de que el
            # consumidor reciba los eventos de un caso en orden.
            ordering_key=event.ordering_key,
            event_id=event.event_id,
            event_type=event.event_type,
            tenant_id=event.tenant_id,
            session_id=event.session_id,
            sequence=str(event.sequence),
            occurred_at=event.occurred_at,
        )
        return str(future.result(timeout=30))

    def publish_batch(self, events: Sequence[IntegrationEvent]) -> tuple[str, ...]:
        return tuple(self.publish(event) for event in sorted(events, key=lambda e: e.sequence))

    def published_for(self, tenant_id: TenantId, session_id: str) -> tuple[IntegrationEvent, ...]:
        raise NotImplementedError(
            "Pub/Sub no permite consultar mensajes ya publicados y Eventarc no ofrece replay. "
            "Falta decidir si se habilita una suscripción de archivo a GCS (coste de "
            "almacenamiento, pero permite reconstruir) o si el expediente de auditoría es la única "
            "fuente de verdad para el reproceso."
        )


__all__ = [
    "CALLBACK_DEFAULT_TIMEOUT_SECONDS",
    "EXECUTION_RETENTION_DAYS",
    "MAX_EXECUTION_DATA_BYTES",
    "MAX_EXPRESSION_LENGTH",
    "MAX_PARALLEL_BRANCHES",
    "MAX_SOURCE_BYTES",
    "CloudWorkflowsSaga",
    "PubSubBus",
]
