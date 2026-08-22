"""Caso de uso: emitir la decisión de la sesión.

Puntos con consecuencias legales, no solo técnicas:

- El **emisor** lo fija la configuración del tenant. Con `SIGNALS_ONLY` el
  middleware entrega señales y evidencias y **no** hay campo de veredicto: es
  obligatorio en Bolivia por el art. 32(II) del Instructivo UIF.
- Solo hay **una decisión por sesión** (invariante I5). Una segunda exige una
  sesión de re-verificación, no una sobrescritura.
- La decisión se sella con el **manifiesto de evidencias**, que es el hash de
  la cadena de auditoría completa. Sin él, la decisión no es reproducible.
- `DECIDED` cierra el proceso; `RETAINED` abre la custodia legal, con
  controles distintos: solo lectura, acceso auditado y sin uso analítico.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from ..domain.decision import Decision, DecisionEngine, DecisionThresholds
from ..domain.enums import (
    DecisionIssuer,
    DecisionOutcome,
    DecisionSource,
    EventType,
    SessionState,
)
from ..domain.events import AuditChain
from ..domain.session import OnboardingSession
from ..domain.value_objects import SessionId, TenantId
from ..errors import DomainError
from ..observability import correlation_scope, get_logger
from ..ports.events_bus import IntegrationEvent

if TYPE_CHECKING:  # pragma: no cover
    from ..container import Container

_logger = get_logger("application.resolve_decision")


@dataclass(frozen=True, slots=True)
class ResolveDecisionCommand:
    """Petición de resolución de la sesión."""

    tenant_id: str
    session_id: str
    principal: str = "svc-orchestrator"
    correlation_id: str | None = None
    seal: bool = True


@dataclass(frozen=True, slots=True)
class ResolveDecisionResult:
    """Decisión emitida, con sus razones auditables."""

    session_id: str
    state: str
    outcome: str
    issuer: str
    risk_level: str
    reasons: tuple[Mapping[str, Any], ...]
    evidence_manifest: str
    review_case_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "outcome": self.outcome,
            "issuer": self.issuer,
            "risk_level": self.risk_level,
            "reasons": [dict(r) for r in self.reasons],
            "evidence_manifest": self.evidence_manifest,
            "review_case_id": self.review_case_id,
        }


class ResolveDecision:
    """Agrega evidencias, emite la decisión y sella el expediente."""

    __slots__ = ("_c",)

    def __init__(self, container: Container) -> None:
        self._c = container

    def execute(self, command: ResolveDecisionCommand) -> ResolveDecisionResult:
        tenant_id = TenantId(command.tenant_id)
        session_id = SessionId(command.session_id)
        with correlation_scope(
            correlation_id=command.correlation_id,
            tenant_id=tenant_id.value,
            session_id=session_id.value,
        ):
            self._c.authorization.assert_authorized(command.principal, tenant_id, "session:decide")
            session = self._c.sessions.get(tenant_id, session_id)
            self._assert_single_decision(session)

            engine = DecisionEngine(
                DecisionThresholds.from_mapping(self._c.config.get_thresholds(tenant_id)),
                issuer=self._c.config.get_decision_issuer(tenant_id),
            )
            trail = self._c.sessions.audit_trail(tenant_id, session_id)
            chain = AuditChain(tenant_id.value, session_id.value, trail)
            chain.verify()  # I8: si la cadena está rota, no se decide.

            decision = engine.evaluate(
                session.evidences,
                decided_by=command.principal,
                source=DecisionSource.AUTOMATED_POLICY,
                evidence_manifest=chain.manifest(),
            )

            session, review_case_id = self._apply(session, decision, chain, command)
            self._c.sessions.save(session, expected_version=None)
            self._publish(tenant_id, session, decision, chain)

            self._c.telemetry.increment(
                "decisions_issued",
                dimensions={"outcome": str(decision.outcome), "risk": str(decision.risk_level)},
            )
            _logger.info(
                "decisión emitida",
                outcome=str(decision.outcome),
                issuer=str(decision.issuer),
                reason_codes=list(decision.reason_codes),
                risk_level=str(decision.risk_level),
            )

            return ResolveDecisionResult(
                session_id=session_id.value,
                state=str(session.state),
                outcome=str(decision.outcome),
                issuer=str(decision.issuer),
                risk_level=str(decision.risk_level),
                reasons=tuple(r.as_dict() for r in decision.reasons),
                evidence_manifest=decision.evidence_manifest,
                review_case_id=review_case_id,
            )

    # -- Auxiliares --------------------------------------------------------

    @staticmethod
    def _assert_single_decision(session: OnboardingSession) -> None:
        if session.state in {SessionState.DECIDED, SessionState.RETAINED, SessionState.PURGED}:
            raise DomainError(
                "la sesión ya tiene decisión; una segunda exige una sesión de re-verificación "
                "(invariante I5)",
                state=str(session.state),
            )

    def _apply(
        self,
        session: OnboardingSession,
        decision: Decision,
        chain: AuditChain,
        command: ResolveDecisionCommand,
    ) -> tuple[OnboardingSession, str | None]:
        if session.state in {SessionState.CREATED, SessionState.COLLECTING}:
            session = session.transition_to(SessionState.PROCESSING)

        needs_review = _needs_review(decision)
        review_case_id: str | None = None

        if needs_review and session.state is SessionState.PROCESSING:
            session = session.transition_to(SessionState.PENDING_REVIEW)
            case = self._c.human_review.open_case(
                session.tenant_id,
                session.session_id,
                reasons=decision.reason_codes,
                priority=_priority(decision),
            )
            review_case_id = case.case_id
            self._c.sessions.append_audit_event(
                chain.append(
                    EventType.REVIEW_OPENED,
                    actor=command.principal,
                    attributes={"case_id": case.case_id, "reasons": list(decision.reason_codes)},
                )
            )
            return session, review_case_id

        if session.state in {SessionState.PROCESSING, SessionState.IN_REVIEW, SessionState.FAILED}:
            session = session.transition_to(SessionState.DECIDED)

        self._c.sessions.append_audit_event(
            chain.append(
                EventType.DECISION_ISSUED,
                actor=command.principal,
                attributes={
                    "outcome": str(decision.outcome),
                    "issuer": str(decision.issuer),
                    "risk_level": str(decision.risk_level),
                    "reason_codes": list(decision.reason_codes),
                    "evidence_manifest": decision.evidence_manifest,
                },
            )
        )
        if command.seal and session.state is SessionState.DECIDED:
            session = session.seal()
            self._c.sessions.append_audit_event(
                chain.append(
                    EventType.RETENTION_APPLIED,
                    actor=command.principal,
                    attributes={"retention_state": str(SessionState.RETAINED)},
                )
            )
        return session, review_case_id

    def _publish(
        self,
        tenant_id: TenantId,
        session: OnboardingSession,
        decision: Decision,
        chain: AuditChain,
    ) -> None:
        head = chain.head
        self._c.events.publish(
            IntegrationEvent(
                event_id=head.event_id if head else session.session_id.value,
                event_type="og.session.decided",
                tenant_id=tenant_id.value,
                session_id=session.session_id.value,
                sequence=head.sequence if head else 0,
                occurred_at=(head.occurred_at.isoformat() if head else ""),
                payload={
                    "outcome": str(decision.outcome),
                    "issuer": str(decision.issuer),
                    "risk_level": str(decision.risk_level),
                    "reason_codes": list(decision.reason_codes),
                    "state": str(session.state),
                },
            )
        )


def _needs_review(decision: Decision) -> bool:
    """`True` si hay que derivar a revisión humana.

    Con `SIGNALS_ONLY` el veredicto de salida no es `MANUAL_REVIEW`, pero las
    razones sí lo indican: la derivación depende de las señales, no de la
    etiqueta final.
    """
    if decision.outcome is DecisionOutcome.MANUAL_REVIEW:
        return True
    if decision.issuer is not DecisionIssuer.SIGNALS_ONLY:
        return False
    from ..domain.decision import (
        REASON_AML_HIT,
        REASON_DOC_INCOHERENT,
        REASON_FACE_GREY_BAND,
        REASON_FORGERY_SUSPECTED,
        REASON_INCONCLUSIVE_STEP,
        REASON_MISSING_EVIDENCE,
        REASON_MRZ_CHECK_DIGIT,
        REASON_OCR_LOW_CONFIDENCE,
        REASON_REGISTRY_MISMATCH,
    )

    review_codes = {
        REASON_AML_HIT,
        REASON_DOC_INCOHERENT,
        REASON_FACE_GREY_BAND,
        REASON_FORGERY_SUSPECTED,
        REASON_INCONCLUSIVE_STEP,
        REASON_MISSING_EVIDENCE,
        REASON_MRZ_CHECK_DIGIT,
        REASON_OCR_LOW_CONFIDENCE,
        REASON_REGISTRY_MISMATCH,
    }
    return bool(set(decision.reason_codes) & review_codes)


def _priority(decision: Decision) -> int:
    """Prioridad del caso de revisión según el riesgo agregado."""
    from ..domain.enums import RiskLevel

    return {RiskLevel.LOW: 30, RiskLevel.MEDIUM: 50, RiskLevel.HIGH: 80, RiskLevel.PROHIBITED: 99}[
        decision.risk_level
    ]


__all__ = ["ResolveDecision", "ResolveDecisionCommand", "ResolveDecisionResult"]
