"""Caso de uso: gestionar la cola de revisión humana.

Se construye a medida porque **ambas nubes abandonaron el HITL gestionado**
(A2I cerrado a clientes nuevos, Document AI HITL apagado el 16/01/2025,
Vertex AI Data Labeling el 03/10/2024). La asimetría desaparece: el mismo
código corre en AWS y en GCP.

Distinciones que el modelo mantiene a propósito:

- `PENDING_REVIEW` frente a `IN_REVIEW`: sin ellas no se puede medir tiempo de
  cola frente a tiempo de trabajo, ni detectar revisores que acaparan casos.
- El revisor **resuelve** y la saga se reanuda con un `ResumeToken`
  persistible, no con un callback abierto: en Cloud Workflows el callback
  tiene 12 h y un solo slot por endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..domain.enums import DecisionOutcome, EventType, SessionState
from ..domain.events import AuditChain
from ..domain.value_objects import SessionId, TenantId
from ..errors import DomainError, ValidationError
from ..observability import correlation_scope, get_logger
from ..ports.saga import ResumeToken

if TYPE_CHECKING:  # pragma: no cover
    from ..container import Container

_logger = get_logger("application.handle_manual_review")

#: Veredictos que un revisor humano puede emitir.
ALLOWED_REVIEW_OUTCOMES: frozenset[DecisionOutcome] = frozenset(
    {DecisionOutcome.APPROVED, DecisionOutcome.REJECTED, DecisionOutcome.INCONCLUSIVE}
)


@dataclass(frozen=True, slots=True)
class AssignCaseCommand:
    """Petición de asignación del siguiente caso de la cola."""

    tenant_id: str
    reviewer: str
    principal: str = "svc-reviewer"
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolveCaseCommand:
    """Resolución emitida por un revisor humano."""

    tenant_id: str
    case_id: str
    reviewer: str
    outcome: str
    notes_digest: str = ""
    principal: str = "svc-reviewer"
    correlation_id: str | None = None
    resume_token: ResumeToken | None = None


@dataclass(frozen=True, slots=True)
class ReviewCaseView:
    """Vista del caso para el revisor. Lleva referencias, no copias de datos."""

    case_id: str
    session_id: str
    state: str
    priority: int
    reasons: tuple[str, ...]
    assigned_to: str | None
    sla_due_at: str | None
    artifact_urls: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "session_id": self.session_id,
            "state": self.state,
            "priority": self.priority,
            "reasons": list(self.reasons),
            "assigned_to": self.assigned_to,
            "sla_due_at": self.sla_due_at,
            "artifact_urls": list(self.artifact_urls),
        }


@dataclass(frozen=True, slots=True)
class ResolveCaseResult:
    """Resultado de cerrar un caso de revisión."""

    case_id: str
    session_id: str
    outcome: str
    session_state: str
    resumed: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "session_id": self.session_id,
            "outcome": self.outcome,
            "session_state": self.session_state,
            "resumed": self.resumed,
        }


class HandleManualReview:
    """Asignación y resolución de casos de revisión humana."""

    __slots__ = ("_c",)

    def __init__(self, container: Container) -> None:
        self._c = container

    def assign_next(self, command: AssignCaseCommand) -> ReviewCaseView | None:
        """Toma el siguiente caso por prioridad y SLA."""
        tenant_id = TenantId(command.tenant_id)
        with correlation_scope(correlation_id=command.correlation_id, tenant_id=tenant_id.value):
            self._c.authorization.assert_authorized(command.principal, tenant_id, "review:read")
            case = self._c.human_review.next_case(tenant_id, command.reviewer)
            if case is None:
                return None

            session_id = SessionId(case.session_id)
            session = self._c.sessions.find(tenant_id, session_id)
            if session is not None and session.state is SessionState.PENDING_REVIEW:
                self._c.sessions.save(
                    session.transition_to(SessionState.IN_REVIEW), expected_version=session.version
                )

            # URLs prefirmadas de corta vida: el revisor mira, no descarga
            # copias permanentes de datos biométricos.
            urls = tuple(
                self._c.storage.presign_get(tenant_id, ref, ttl_seconds=300)
                for ref in case.artifacts
            )
            _logger.info(
                "caso asignado",
                case_id=case.case_id,
                priority=case.priority,
                reasons=list(case.reasons),
            )
            return ReviewCaseView(
                case_id=case.case_id,
                session_id=case.session_id,
                state=case.state,
                priority=case.priority,
                reasons=case.reasons,
                assigned_to=case.assigned_to,
                sla_due_at=case.sla_due_at.isoformat() if case.sla_due_at else None,
                artifact_urls=urls,
            )

    def resolve(self, command: ResolveCaseCommand) -> ResolveCaseResult:
        """Cierra el caso, decide la sesión y reanuda la saga."""
        tenant_id = TenantId(command.tenant_id)
        outcome = _coerce_outcome(command.outcome)
        with correlation_scope(correlation_id=command.correlation_id, tenant_id=tenant_id.value):
            self._c.authorization.assert_authorized(command.principal, tenant_id, "review:resolve")
            case = self._c.human_review.get_case(tenant_id, command.case_id)
            if case is None:
                raise DomainError("caso de revisión inexistente", case_id=command.case_id)
            if case.assigned_to not in {command.reviewer, None}:
                raise DomainError(
                    "el caso está asignado a otro revisor",
                    case_id=command.case_id,
                )

            resolution = self._c.human_review.resolve(
                tenant_id,
                command.case_id,
                outcome=outcome,
                reviewer=command.reviewer,
                notes_digest=command.notes_digest,
            )

            session_id = SessionId(case.session_id)
            session = self._c.sessions.get(tenant_id, session_id)
            chain = AuditChain(
                tenant_id.value, session_id.value, self._c.sessions.audit_trail(tenant_id, session_id)
            )
            if session.state is SessionState.PENDING_REVIEW:
                session = session.transition_to(SessionState.IN_REVIEW)
            if session.state is SessionState.IN_REVIEW:
                session = session.transition_to(SessionState.DECIDED).seal()
            self._c.sessions.save(session, expected_version=None)

            self._c.sessions.append_audit_event(
                chain.append(
                    EventType.REVIEW_RESOLVED,
                    actor=command.reviewer,
                    attributes={
                        "case_id": command.case_id,
                        "outcome": str(outcome),
                        "notes_digest": resolution.notes_digest,
                    },
                )
            )

            resumed = False
            token = command.resume_token
            if token is not None:
                self._c.saga.resume(token, {"outcome": str(outcome), "case_id": command.case_id})
                resumed = True

            self._c.telemetry.increment(
                "reviews_resolved", dimensions={"outcome": str(outcome)}
            )
            return ResolveCaseResult(
                case_id=command.case_id,
                session_id=case.session_id,
                outcome=str(outcome),
                session_state=str(session.state),
                resumed=resumed,
            )

    def queue_depth(self, tenant_id: str) -> dict[str, int]:
        """Conteo por estado, base de la métrica de cola y de la alerta de SLA."""
        return dict(self._c.human_review.pending_count(TenantId(tenant_id)))


def _coerce_outcome(value: str) -> DecisionOutcome:
    try:
        outcome = DecisionOutcome(value.strip().upper())
    except ValueError as exc:
        allowed = ", ".join(sorted(o.value for o in ALLOWED_REVIEW_OUTCOMES))
        raise ValidationError(
            f"veredicto de revisión desconocido '{value}'; admitidos: {allowed}", field="outcome"
        ) from exc
    if outcome not in ALLOWED_REVIEW_OUTCOMES:
        allowed = ", ".join(sorted(o.value for o in ALLOWED_REVIEW_OUTCOMES))
        raise ValidationError(
            f"un revisor no puede emitir '{outcome}'; admitidos: {allowed}", field="outcome"
        )
    return outcome


__all__ = [
    "ALLOWED_REVIEW_OUTCOMES",
    "AssignCaseCommand",
    "HandleManualReview",
    "ResolveCaseCommand",
    "ResolveCaseResult",
    "ReviewCaseView",
]
