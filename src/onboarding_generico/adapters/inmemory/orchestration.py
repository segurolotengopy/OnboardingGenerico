"""Saga, revisión humana, bus de eventos y telemetría en memoria.

La saga en memoria reproduce las **propiedades** que exige el puerto, no la
mecánica de ningún orquestador:

- La suspensión devuelve un `ResumeToken` **persistible**, no un puntero en
  memoria del orquestador.
- `resume` es **idempotente**: reanudar dos veces con el mismo token no
  produce dos avances. Es indispensable porque Firestore + Eventarc no
  garantiza orden ni permite replay.
- El contexto solo lleva punteros y metadatos, para respetar el límite
  dominante de 512 KB acumulados por ejecución de Cloud Workflows.
"""

from __future__ import annotations

import threading
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from ...domain.enums import DecisionOutcome
from ...domain.value_objects import ObjectRef, SessionId, TenantId, utc_now
from ...errors import DomainError, ValidationError
from ...ports.events_bus import EventBusPort, IntegrationEvent
from ...ports.human_review import HumanReviewPort, ReviewCase, ReviewResolution
from ...ports.saga import OnboardingSagaPort, ResumeToken, SagaHandle, SagaStatus
from ...ports.telemetry import FORBIDDEN_DIMENSIONS, TelemetryPort


class InMemorySaga(OnboardingSagaPort):
    """Saga en memoria con reanudación idempotente."""

    __slots__ = ("_consumed", "_counter", "_executions", "_lock", "_tokens")

    def __init__(self) -> None:
        self._executions: dict[str, dict[str, Any]] = {}
        self._tokens: dict[str, str] = {}
        self._consumed: set[str] = set()
        self._lock = threading.RLock()
        self._counter = 0

    def start_verification(
        self,
        tenant_id: TenantId,
        session_id: SessionId,
        *,
        plan: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> SagaHandle:
        _assert_pointers_only(context or {})
        with self._lock:
            self._counter += 1
            execution_id = f"exec-{tenant_id.value}-{self._counter}"
            self._executions[execution_id] = {
                "tenant_id": tenant_id.value,
                "session_id": session_id.value,
                "state": "RUNNING",
                "plan": dict(plan),
                "context": dict(context or {}),
                "current_step": None,
                "suspended": False,
                "resumes": 0,
            }
        return SagaHandle(
            execution_id=execution_id,
            tenant_id=tenant_id.value,
            session_id=session_id.value,
            started_at=utc_now().isoformat(),
            orchestrator="inmemory",
        )

    def await_manual_decision(
        self, handle: SagaHandle, *, reason: str, ttl_seconds: int = 604_800
    ) -> ResumeToken:
        with self._lock:
            execution = self._require(handle.execution_id)
            execution["state"] = "SUSPENDED"
            execution["suspended"] = True
            token_value = uuid.uuid4().hex
            self._tokens[token_value] = handle.execution_id
        return ResumeToken(
            value=token_value,
            session_id=handle.session_id,
            tenant_id=handle.tenant_id,
            expires_at=(datetime.now(UTC) + timedelta(seconds=ttl_seconds)).isoformat(),
            reason=reason,
        )

    def resume(self, token: ResumeToken, payload: Mapping[str, Any]) -> SagaHandle:
        _assert_pointers_only(payload)
        with self._lock:
            execution_id = self._tokens.get(token.value)
            if execution_id is None:
                raise DomainError("token de reanudación desconocido o ya caducado")
            execution = self._require(execution_id)
            if token.value in self._consumed:
                # Idempotencia: la segunda reanudación no avanza nada.
                return self._handle(execution_id, execution)
            self._consumed.add(token.value)
            execution["state"] = "RUNNING"
            execution["suspended"] = False
            execution["resumes"] += 1
            execution["context"].update(dict(payload))
            return self._handle(execution_id, execution)

    def status(self, handle: SagaHandle) -> SagaStatus:
        with self._lock:
            execution = self._require(handle.execution_id)
            return SagaStatus(
                execution_id=handle.execution_id,
                state=str(execution["state"]),
                current_step=execution["current_step"],
                suspended=bool(execution["suspended"]),
                context=dict(execution["context"]),
            )

    def compensate(self, handle: SagaHandle, *, reason: str) -> SagaStatus:
        with self._lock:
            execution = self._require(handle.execution_id)
            execution["state"] = "COMPENSATED"
            execution["context"]["compensation_reason"] = reason
        return self.status(handle)

    def abort(self, handle: SagaHandle, *, reason: str) -> SagaStatus:
        with self._lock:
            execution = self._require(handle.execution_id)
            execution["state"] = "ABORTED"
            execution["context"]["abort_reason"] = reason
        return self.status(handle)

    def advance(self, handle: SagaHandle, step_id: str) -> SagaStatus:
        """Utilidad de prueba: marca el paso en curso."""
        with self._lock:
            self._require(handle.execution_id)["current_step"] = step_id
        return self.status(handle)

    def _require(self, execution_id: str) -> dict[str, Any]:
        execution = self._executions.get(execution_id)
        if execution is None:
            raise DomainError("ejecución de saga desconocida", execution_id=execution_id)
        return execution

    @staticmethod
    def _handle(execution_id: str, execution: Mapping[str, Any]) -> SagaHandle:
        return SagaHandle(
            execution_id=execution_id,
            tenant_id=str(execution["tenant_id"]),
            session_id=str(execution["session_id"]),
            started_at=utc_now().isoformat(),
            orchestrator="inmemory",
        )


def _assert_pointers_only(payload: Mapping[str, Any], *, limit_bytes: int = 262_144) -> None:
    """Rechaza payloads con binarios o con tamaño de riesgo.

    Es una verificación real, no decorativa: si el contexto de la saga crece,
    el flujo deja de caber en Cloud Workflows (512 KB acumulados) mucho antes
    de agotar el payload de Step Functions (256 KiB).
    """
    import json

    for key, value in payload.items():
        if isinstance(value, (bytes, bytearray)):
            raise ValidationError(
                "ningún binario puede viajar por el estado del orquestador; use un ObjectRef",
                field=key,
            )
    encoded = json.dumps(dict(payload), default=str).encode("utf-8")
    if len(encoded) > limit_bytes:
        raise ValidationError(
            "el contexto de la saga supera el límite de payload",
            size_bytes=len(encoded),
            limit_bytes=limit_bytes,
        )


class InMemoryHumanReview(HumanReviewPort):
    """Cola de revisión propia, con prioridad y SLA.

    Se construye a medida porque ambas nubes abandonaron el HITL gestionado
    (A2I cerrado a clientes nuevos, Document AI HITL apagado el 16/01/2025,
    Vertex AI Data Labeling el 03/10/2024).
    """

    __slots__ = ("_cases", "_counter", "_lock", "_resolutions")

    def __init__(self) -> None:
        self._cases: dict[tuple[str, str], ReviewCase] = {}
        self._resolutions: list[ReviewResolution] = []
        self._lock = threading.RLock()
        self._counter = 0

    def open_case(
        self,
        tenant_id: TenantId,
        session_id: SessionId,
        *,
        reasons: Sequence[str],
        priority: int = 50,
        sla_seconds: int = 86_400,
        resume_token: str = "",
        artifacts: Sequence[ObjectRef] = (),
    ) -> ReviewCase:
        with self._lock:
            self._counter += 1
            case_id = f"rev-{tenant_id.value}-{self._counter}"
            case = ReviewCase(
                case_id=case_id,
                tenant_id=tenant_id.value,
                session_id=session_id.value,
                priority=priority,
                state="PENDING_REVIEW",
                reasons=tuple(reasons),
                sla_due_at=utc_now() + timedelta(seconds=sla_seconds),
                resume_token=resume_token,
                artifacts=tuple(artifacts),
                created_at=utc_now(),
            )
            self._cases[(tenant_id.value, case_id)] = case
            return case

    def next_case(self, tenant_id: TenantId, reviewer: str) -> ReviewCase | None:
        with self._lock:
            pending = [
                case
                for (tid, _), case in self._cases.items()
                if tid == tenant_id.value and case.state == "PENDING_REVIEW"
            ]
            if not pending:
                return None
            # Prioridad descendente y, a igualdad, el más antiguo primero.
            pending.sort(key=lambda c: (-c.priority, c.created_at or utc_now()))
            chosen = pending[0]
            assigned = ReviewCase(
                case_id=chosen.case_id,
                tenant_id=chosen.tenant_id,
                session_id=chosen.session_id,
                priority=chosen.priority,
                state="IN_REVIEW",
                reasons=chosen.reasons,
                assigned_to=reviewer,
                sla_due_at=chosen.sla_due_at,
                resume_token=chosen.resume_token,
                artifacts=chosen.artifacts,
                created_at=chosen.created_at,
            )
            self._cases[(tenant_id.value, chosen.case_id)] = assigned
            return assigned

    def release_case(self, tenant_id: TenantId, case_id: str) -> ReviewCase:
        with self._lock:
            case = self._cases.get((tenant_id.value, case_id))
            if case is None:
                raise DomainError("caso de revisión inexistente", case_id=case_id)
            released = ReviewCase(
                case_id=case.case_id,
                tenant_id=case.tenant_id,
                session_id=case.session_id,
                priority=case.priority,
                state="PENDING_REVIEW",
                reasons=case.reasons,
                assigned_to=None,
                sla_due_at=case.sla_due_at,
                resume_token=case.resume_token,
                artifacts=case.artifacts,
                created_at=case.created_at,
            )
            self._cases[(tenant_id.value, case_id)] = released
            return released

    def resolve(
        self,
        tenant_id: TenantId,
        case_id: str,
        *,
        outcome: DecisionOutcome,
        reviewer: str,
        notes_digest: str = "",
    ) -> ReviewResolution:
        with self._lock:
            case = self._cases.get((tenant_id.value, case_id))
            if case is None:
                raise DomainError("caso de revisión inexistente", case_id=case_id)
            if case.state == "RESOLVED":
                raise DomainError("el caso ya fue resuelto", case_id=case_id)
            self._cases[(tenant_id.value, case_id)] = ReviewCase(
                case_id=case.case_id,
                tenant_id=case.tenant_id,
                session_id=case.session_id,
                priority=case.priority,
                state="RESOLVED",
                reasons=case.reasons,
                assigned_to=reviewer,
                sla_due_at=case.sla_due_at,
                resume_token=case.resume_token,
                artifacts=case.artifacts,
                created_at=case.created_at,
            )
            resolution = ReviewResolution(
                case_id=case_id,
                outcome=outcome,
                reviewer=reviewer,
                notes_digest=notes_digest,
                resolved_at=utc_now(),
            )
            self._resolutions.append(resolution)
            return resolution

    def get_case(self, tenant_id: TenantId, case_id: str) -> ReviewCase | None:
        with self._lock:
            return self._cases.get((tenant_id.value, case_id))

    def pending_count(self, tenant_id: TenantId) -> Mapping[str, int]:
        with self._lock:
            counter: Counter[str] = Counter(
                case.state for (tid, _), case in self._cases.items() if tid == tenant_id.value
            )
        return dict(counter)

    @property
    def resolutions(self) -> tuple[ReviewResolution, ...]:
        with self._lock:
            return tuple(self._resolutions)


class InMemoryEventBus(EventBusPort):
    """Bus de eventos con deduplicación por `event_id` y orden por secuencia."""

    __slots__ = ("_events", "_lock", "_seen")

    def __init__(self) -> None:
        self._events: list[IntegrationEvent] = []
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def publish(self, event: IntegrationEvent) -> str:
        with self._lock:
            if event.event_id in self._seen:
                # Consumidor idempotente: republicar no duplica.
                return event.event_id
            self._seen.add(event.event_id)
            self._events.append(event)
            return event.event_id

    def publish_batch(self, events: Sequence[IntegrationEvent]) -> tuple[str, ...]:
        return tuple(self.publish(event) for event in sorted(events, key=lambda e: e.sequence))

    def published_for(self, tenant_id: TenantId, session_id: str) -> tuple[IntegrationEvent, ...]:
        with self._lock:
            matches = [
                e
                for e in self._events
                if e.tenant_id == tenant_id.value and e.session_id == session_id
            ]
        matches.sort(key=lambda e: e.sequence)
        return tuple(matches)

    @property
    def all_events(self) -> tuple[IntegrationEvent, ...]:
        with self._lock:
            return tuple(self._events)


class InMemoryTelemetry(TelemetryPort):
    """Telemetría en memoria que **rechaza** dimensiones prohibidas."""

    __slots__ = ("_counters", "_gauges", "_lock", "_observations")

    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()
        self._observations: dict[str, list[float]] = {}
        self._gauges: dict[str, float] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(name: str, dimensions: Mapping[str, str] | None) -> str:
        if not dimensions:
            return name
        offending = sorted(set(dimensions) & FORBIDDEN_DIMENSIONS)
        if offending:
            raise ValidationError(
                "dimensión de métrica prohibida: alta cardinalidad o PII",
                field="dimensions",
                offending=offending,
            )
        suffix = ",".join(f"{k}={dimensions[k]}" for k in sorted(dimensions))
        return f"{name}{{{suffix}}}"

    def increment(
        self, name: str, *, value: int = 1, dimensions: Mapping[str, str] | None = None
    ) -> None:
        key = self._key(name, dimensions)
        with self._lock:
            self._counters[key] += value

    def observe(
        self, name: str, value: float, *, dimensions: Mapping[str, str] | None = None
    ) -> None:
        key = self._key(name, dimensions)
        with self._lock:
            self._observations.setdefault(key, []).append(value)

    def gauge(
        self, name: str, value: float, *, dimensions: Mapping[str, str] | None = None
    ) -> None:
        key = self._key(name, dimensions)
        with self._lock:
            self._gauges[key] = value

    def snapshot(self) -> Mapping[str, float]:
        with self._lock:
            data: dict[str, float] = {k: float(v) for k, v in self._counters.items()}
            for key, values in self._observations.items():
                data[f"{key}#count"] = float(len(values))
                data[f"{key}#sum"] = float(sum(values))
            data.update(self._gauges)
            return data


__all__ = [
    "InMemoryEventBus",
    "InMemoryHumanReview",
    "InMemorySaga",
    "InMemoryTelemetry",
]
