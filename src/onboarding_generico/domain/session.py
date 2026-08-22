"""Agregado `OnboardingSession`: máquina de estados e invariantes.

La sesión es la **raíz de agregación transaccional**. Todo lo que cambia
dentro de ella cambia bajo su bloqueo optimista (`version`).

Las transiciones válidas se declaran en `ALLOWED_TRANSITIONS`, que es una
transcripción directa del diagrama de estados del doc 03 §3. Cualquier
transición no declarada lanza `InvalidStateTransitionError`: no existe una
ruta silenciosa entre estados.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any, Mapping

from ..errors import DomainError, InvalidStateTransitionError, ValidationError
from .enums import (
    ArtifactSlot,
    Capability,
    DataClass,
    DocumentType,
    SessionState,
    StepState,
)
from .value_objects import (
    Artifact,
    Evidence,
    FlowSpecRef,
    ObjectRef,
    ProviderRef,
    SessionId,
    SubjectRef,
    TenantId,
    utc_now,
)

#: Transiciones permitidas de la sesión (doc 03 §3).
ALLOWED_TRANSITIONS: dict[SessionState, frozenset[SessionState]] = {
    SessionState.CREATED: frozenset(
        {SessionState.COLLECTING, SessionState.EXPIRED, SessionState.CANCELLED}
    ),
    SessionState.COLLECTING: frozenset(
        {
            SessionState.COLLECTING,
            SessionState.PROCESSING,
            SessionState.EXPIRED,
            SessionState.ABANDONED,
            SessionState.CANCELLED,
        }
    ),
    SessionState.PROCESSING: frozenset(
        {
            SessionState.AWAITING_SUBJECT,
            SessionState.PENDING_REVIEW,
            SessionState.DECIDED,
            SessionState.FAILED,
        }
    ),
    SessionState.AWAITING_SUBJECT: frozenset({SessionState.PROCESSING, SessionState.EXPIRED}),
    SessionState.PENDING_REVIEW: frozenset({SessionState.IN_REVIEW}),
    SessionState.IN_REVIEW: frozenset(
        {SessionState.PENDING_REVIEW, SessionState.PROCESSING, SessionState.DECIDED}
    ),
    SessionState.FAILED: frozenset({SessionState.PROCESSING, SessionState.DECIDED}),
    SessionState.DECIDED: frozenset({SessionState.RETAINED}),
    SessionState.RETAINED: frozenset({SessionState.BLOCKED, SessionState.PURGED}),
    SessionState.BLOCKED: frozenset({SessionState.RETAINED, SessionState.PURGED}),
    SessionState.EXPIRED: frozenset({SessionState.PURGED}),
    SessionState.ABANDONED: frozenset({SessionState.PURGED}),
    SessionState.CANCELLED: frozenset({SessionState.PURGED}),
    SessionState.PURGED: frozenset(),
}

#: Estados terminales del proceso: no admiten nuevos pasos ni artefactos (I4).
TERMINAL_STATES: frozenset[SessionState] = frozenset(
    {
        SessionState.DECIDED,
        SessionState.RETAINED,
        SessionState.BLOCKED,
        SessionState.EXPIRED,
        SessionState.ABANDONED,
        SessionState.CANCELLED,
        SessionState.PURGED,
    }
)

#: Estados terminales de un paso.
STEP_TERMINAL_STATES: frozenset[StepState] = frozenset(
    {
        StepState.SUCCEEDED,
        StepState.NEGATIVE,
        StepState.INCONCLUSIVE,
        StepState.FAILED,
        StepState.SKIPPED,
    }
)

#: Estados terminales de un paso que satisfacen una dependencia (I2).
STEP_SATISFYING_STATES: frozenset[StepState] = frozenset(
    {StepState.SUCCEEDED, StepState.NEGATIVE, StepState.SKIPPED}
)


@dataclass(frozen=True, slots=True)
class Step:
    """Paso de la sesión. Inmutable: avanzar produce una copia nueva."""

    step_id: str
    capability: Capability
    depends_on: tuple[str, ...] = ()
    state: StepState = StepState.PENDING
    provider: ProviderRef | None = None
    attempts: int = 0
    required: bool = True
    evidence_id: str | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.state in STEP_TERMINAL_STATES

    @property
    def satisfies_dependency(self) -> bool:
        return self.state in STEP_SATISFYING_STATES


@dataclass(frozen=True, slots=True)
class OnboardingSession:
    """Raíz de agregación de la sesión de onboarding."""

    session_id: SessionId
    tenant_id: TenantId
    subject: SubjectRef
    country: str
    document_type: DocumentType
    tier: str
    spec_ref: FlowSpecRef
    state: SessionState = SessionState.CREATED
    version: int = 0
    created_at: datetime = field(default_factory=utc_now)
    expires_at: datetime | None = None
    steps: tuple[Step, ...] = ()
    artifacts: tuple[Artifact, ...] = ()
    evidences: tuple[Evidence, ...] = ()
    external_ref: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    # -- Consultas --------------------------------------------------------

    def step(self, step_id: str) -> Step:
        for candidate in self.steps:
            if candidate.step_id == step_id:
                return candidate
        raise DomainError("paso inexistente en la sesión", step_id=step_id)

    def has_step(self, step_id: str) -> bool:
        return any(candidate.step_id == step_id for candidate in self.steps)

    def artifact(self, slot: ArtifactSlot) -> Artifact | None:
        for candidate in self.artifacts:
            if candidate.slot is slot:
                return candidate
        return None

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES

    @property
    def pending_steps(self) -> tuple[Step, ...]:
        return tuple(s for s in self.steps if not s.is_terminal)

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if self.expires_at is None:
            return False
        return (now or utc_now()) >= self.expires_at

    def can_run(self, step_id: str) -> bool:
        """Invariante I2: un paso solo corre si todas sus dependencias cerraron bien."""
        target = self.step(step_id)
        if target.is_terminal:
            return False
        for dependency_id in target.depends_on:
            if not self.step(dependency_id).satisfies_dependency:
                return False
        return True

    def ready_steps(self) -> tuple[Step, ...]:
        """Pasos cuyas dependencias ya están satisfechas."""
        return tuple(s for s in self.steps if not s.is_terminal and self.can_run(s.step_id))

    # -- Comandos ---------------------------------------------------------

    @classmethod
    def start(
        cls,
        *,
        tenant_id: TenantId,
        subject: SubjectRef,
        country: str,
        document_type: DocumentType,
        tier: str,
        spec_ref: FlowSpecRef,
        steps: tuple[Step, ...],
        ttl_seconds: int,
        external_ref: str | None = None,
        session_id: SessionId | None = None,
        now: datetime | None = None,
    ) -> OnboardingSession:
        """Crea la sesión en estado `CREATED` con su plan de pasos congelado."""
        if not steps:
            raise ValidationError("una sesión exige al menos un paso", field="steps")
        _assert_acyclic(steps)
        moment = now or utc_now()
        return cls(
            session_id=session_id or SessionId.generate(),
            tenant_id=tenant_id,
            subject=subject,
            country=country,
            document_type=document_type,
            tier=tier,
            spec_ref=spec_ref,
            state=SessionState.CREATED,
            version=1,
            created_at=moment,
            expires_at=moment + timedelta(seconds=ttl_seconds),
            steps=steps,
            external_ref=external_ref,
        )

    def transition_to(self, target: SessionState) -> OnboardingSession:
        """Aplica una transición de estado, validándola contra la máquina."""
        allowed = ALLOWED_TRANSITIONS.get(self.state, frozenset())
        if target not in allowed:
            raise InvalidStateTransitionError(str(self.state), str(target))
        return replace(self, state=target, version=self.version + 1)

    def register_artifact(self, artifact: Artifact) -> OnboardingSession:
        """Añade o reemplaza un artefacto por su ranura.

        Invariante I4: una sesión terminal no admite artefactos nuevos.
        """
        self._assert_mutable("registrar artefacto")
        if self.state not in {SessionState.CREATED, SessionState.COLLECTING, SessionState.AWAITING_SUBJECT}:
            raise DomainError(
                "solo se aceptan artefactos durante la captura",
                state=str(self.state),
            )
        remaining = tuple(a for a in self.artifacts if a.slot is not artifact.slot)
        state = SessionState.COLLECTING if self.state is SessionState.CREATED else self.state
        return replace(
            self,
            artifacts=remaining + (artifact,),
            state=state,
            version=self.version + 1,
        )

    def start_step(self, step_id: str, provider: ProviderRef, *, now: datetime | None = None) -> OnboardingSession:
        """Marca un paso como `RUNNING`, validando la invariante I2."""
        self._assert_mutable("iniciar paso")
        if not self.can_run(step_id):
            raise DomainError(
                "el paso tiene dependencias sin satisfacer (invariante I2)",
                step_id=step_id,
            )
        target = self.step(step_id)
        updated = replace(
            target,
            state=StepState.RUNNING,
            provider=provider,
            attempts=target.attempts + 1,
            started_at=now or utc_now(),
        )
        return self._with_step(updated)

    def complete_step(
        self,
        step_id: str,
        *,
        state: StepState,
        evidence: Evidence | None = None,
        error_code: str | None = None,
        now: datetime | None = None,
    ) -> OnboardingSession:
        """Cierra un paso en un estado terminal y sella su evidencia (I3)."""
        self._assert_mutable("cerrar paso")
        if state not in STEP_TERMINAL_STATES:
            raise DomainError("estado de cierre no terminal", step_id=step_id, state=str(state))
        target = self.step(step_id)
        updated = replace(
            target,
            state=state,
            evidence_id=evidence.evidence_id if evidence else target.evidence_id,
            error_code=error_code,
            finished_at=now or utc_now(),
        )
        session = self._with_step(updated)
        if evidence is not None:
            session = replace(session, evidences=session.evidences + (evidence,))
        return session

    def begin_processing(self) -> OnboardingSession:
        """`COLLECTING -> PROCESSING` cuando los artefactos están completos."""
        return self.transition_to(SessionState.PROCESSING)

    def require_subject_action(self) -> OnboardingSession:
        """`PROCESSING -> AWAITING_SUBJECT`: recaptura o reto adicional."""
        return self.transition_to(SessionState.AWAITING_SUBJECT)

    def seal(self) -> OnboardingSession:
        """`DECIDED -> RETAINED`: cierra el expediente y abre la custodia legal."""
        return self.transition_to(SessionState.RETAINED)

    def block(self) -> OnboardingSession:
        """Limitación del tratamiento (art. 18 GDPR). **No es un borrado.**"""
        return self.transition_to(SessionState.BLOCKED)

    def purge(self) -> OnboardingSession:
        """Estado terminal con expediente eliminado o crypto-shredded."""
        return replace(
            self.transition_to(SessionState.PURGED),
            artifacts=(),
            evidences=(),
            attributes={},
        )

    # -- Interno ----------------------------------------------------------

    def _with_step(self, updated: Step) -> OnboardingSession:
        steps = tuple(updated if s.step_id == updated.step_id else s for s in self.steps)
        return replace(self, steps=steps, version=self.version + 1)

    def _assert_mutable(self, action: str) -> None:
        if self.is_terminal:
            raise DomainError(
                f"no se puede {action} en una sesión terminal (invariante I4)",
                state=str(self.state),
            )


def _assert_acyclic(steps: tuple[Step, ...]) -> None:
    """Verifica que el grafo de dependencias es acíclico y está completo."""
    known = {s.step_id for s in steps}
    if len(known) != len(steps):
        raise ValidationError("hay identificadores de paso duplicados", field="steps")
    for step in steps:
        for dependency in step.depends_on:
            if dependency not in known:
                raise ValidationError(
                    "dependencia hacia un paso inexistente",
                    field="depends_on",
                    step_id=step.step_id,
                    missing=dependency,
                )

    state: dict[str, int] = {s.step_id: 0 for s in steps}
    graph = {s.step_id: tuple(s.depends_on) for s in steps}

    def visit(node: str, path: tuple[str, ...]) -> None:
        if state[node] == 1:
            raise ValidationError(
                "ciclo en el grafo de dependencias",
                field="depends_on",
                cycle=list(path + (node,)),
            )
        if state[node] == 2:
            return
        state[node] = 1
        for neighbour in graph[node]:
            visit(neighbour, path + (node,))
        state[node] = 2

    for step in steps:
        visit(step.step_id, ())


def build_selfie_artifact(
    ref: ObjectRef, *, purgeable_after_seconds: int = 86_400, now: datetime | None = None
) -> Artifact:
    """Crea el artefacto de selfie con la fecha de purga que exige la I7."""
    moment = now or utc_now()
    return Artifact(
        slot=ArtifactSlot.SELFIE,
        ref=ref,
        data_class=DataClass.BIOMETRIC,
        captured_at=moment,
        purgeable_from=moment + timedelta(seconds=purgeable_after_seconds),
    )


__all__ = [
    "ALLOWED_TRANSITIONS",
    "STEP_SATISFYING_STATES",
    "STEP_TERMINAL_STATES",
    "TERMINAL_STATES",
    "OnboardingSession",
    "Step",
    "build_selfie_artifact",
]
