"""Caso de uso: registrar la selfie y ejecutar liveness y comparación facial.

Orden deliberado: **liveness primero, face match después**. Comparar contra
una imagen que no superó el reto de vivacidad es gastar cómputo y, peor,
producir una similitud alta con una presentación de ataque.

Reglas que este caso de uso hace cumplir:

- El artefacto de selfie es de clase `BIOMETRIC` y exige `purgeable_from`
  (invariante I7): un dato biométrico sin fecha de purga es retención
  indefinida de categoría especial.
- Una inyección detectada es terminal: **no se reintenta ni se degrada** a un
  proveedor sin certificación iBeta.
- La similitud en banda gris no fuerza un binario: deriva a revisión humana.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from ..domain.enums import (
    ArtifactSlot,
    Capability,
    EventType,
    EvidenceKind,
    StepState,
    Verdict,
)
from ..domain.events import AuditChain
from ..domain.session import OnboardingSession, build_selfie_artifact
from ..domain.value_objects import Evidence, ObjectRef, ProviderRef, SessionId, TenantId
from ..errors import ValidationError
from ..observability import correlation_scope, get_logger

if TYPE_CHECKING:  # pragma: no cover
    from ..container import Container

_logger = get_logger("application.submit_selfie")


@dataclass(frozen=True, slots=True)
class SubmitSelfieCommand:
    """Petición de procesamiento biométrico."""

    tenant_id: str
    session_id: str
    object_key: str
    sha256: str
    liveness_session_id: str | None = None
    content_type: str = "image/jpeg"
    size_bytes: int = 0
    principal: str = "svc-requester"
    correlation_id: str | None = None
    purge_after_seconds: int = 86_400


@dataclass(frozen=True, slots=True)
class SubmitSelfieResult:
    """Resultado biométrico, con puntuaciones pero sin imágenes ni embeddings."""

    session_id: str
    state: str
    liveness_score: float
    liveness_passed: bool
    injection_detected: bool
    similarity: float
    matched: bool
    grey_band: bool
    steps: Mapping[str, str]
    evidence_ids: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "liveness": {
                "score": self.liveness_score,
                "passed": self.liveness_passed,
                "injection_detected": self.injection_detected,
            },
            "face_match": {
                "similarity": self.similarity,
                "matched": self.matched,
                "grey_band": self.grey_band,
            },
            "steps": dict(self.steps),
            "evidence_ids": list(self.evidence_ids),
        }


class SubmitSelfie:
    """Ejecuta liveness y comparación facial sobre la sesión."""

    __slots__ = ("_c",)

    def __init__(self, container: Container) -> None:
        self._c = container

    def execute(self, command: SubmitSelfieCommand) -> SubmitSelfieResult:
        tenant_id = TenantId(command.tenant_id)
        session_id = SessionId(command.session_id)
        with correlation_scope(
            correlation_id=command.correlation_id,
            tenant_id=tenant_id.value,
            session_id=session_id.value,
        ):
            self._c.authorization.assert_authorized(
                command.principal, tenant_id, "session:submit_artifact"
            )
            session = self._c.sessions.get(tenant_id, session_id)
            selfie_ref = self._register_selfie(tenant_id, session, command)
            session = self._c.sessions.get(tenant_id, session_id)

            chain = AuditChain(
                tenant_id.value, session_id.value, self._c.sessions.audit_trail(tenant_id, session_id)
            )
            steps: dict[str, str] = {}
            evidences: list[Evidence] = []

            liveness, session = self._run_liveness(
                tenant_id, session, command, steps, evidences, chain
            )

            similarity = 0.0
            matched = False
            grey_band = False
            if liveness.passed:
                similarity, matched, grey_band, session = self._run_face_match(
                    tenant_id, session, liveness.audited_image or selfie_ref, selfie_ref,
                    steps, evidences, chain, command,
                )
            else:
                _logger.warning(
                    "liveness no superado: se omite la comparación facial",
                    injection_detected=liveness.injection_detected,
                    score=liveness.score,
                )

            self._c.sessions.save(session, expected_version=None)
            self._c.telemetry.observe("liveness_score", liveness.score)
            if liveness.passed:
                self._c.telemetry.observe("face_similarity", similarity)

            return SubmitSelfieResult(
                session_id=session_id.value,
                state=str(session.state),
                liveness_score=liveness.score,
                liveness_passed=liveness.passed,
                injection_detected=liveness.injection_detected,
                similarity=similarity,
                matched=matched,
                grey_band=grey_band,
                steps=steps,
                evidence_ids=tuple(e.evidence_id for e in evidences),
            )

    # -- Pasos -------------------------------------------------------------

    def _register_selfie(
        self, tenant_id: TenantId, session: OnboardingSession, command: SubmitSelfieCommand
    ) -> ObjectRef:
        ref = ObjectRef.build(
            scheme={"aws": "s3", "gcp": "gs"}.get(self._c.settings.cloud_provider, "mem"),
            bucket=self._c.settings.artifact_bucket,
            key=_scoped_key(tenant_id, command.object_key),
            sha256=command.sha256,
            size_bytes=command.size_bytes,
            content_type=command.content_type,
        )
        if not self._c.storage.exists(tenant_id, ref):
            raise ValidationError(
                "la selfie no está en el almacén: cárguela con la URL prefirmada",
                field="object_key",
            )
        self._c.storage.get(tenant_id, ref)  # I6
        artifact = build_selfie_artifact(ref, purgeable_after_seconds=command.purge_after_seconds)
        updated = session.register_artifact(artifact)
        self._c.sessions.save(updated, expected_version=session.version)
        return ref

    def _run_liveness(
        self,
        tenant_id: TenantId,
        session: OnboardingSession,
        command: SubmitSelfieCommand,
        steps: dict[str, str],
        evidences: list[Evidence],
        chain: AuditChain,
    ) -> tuple[Any, OnboardingSession]:
        step_id = _find_step(session, Capability.BIOMETRICS_LIVENESS)
        provider_session_id = command.liveness_session_id
        if provider_session_id is None:
            provider_session_id = self._c.liveness.create_session(tenant_id).provider_session_id
        result = self._c.liveness.get_result(
            tenant_id, provider_session_id, threshold=self._c.settings.liveness_min_score
        )
        if step_id is None:
            return result, session

        provider = ProviderRef(result.provider_id, result.pad_level)
        evidence = Evidence.create(
            step_id=step_id,
            kind=EvidenceKind.LIVENESS,
            provider=provider,
            verdict=Verdict.PASS if result.passed else Verdict.FAIL,
            scores={
                "liveness_score": result.score,
                "injection_detected": 1.0 if result.injection_detected else 0.0,
            },
            thresholds={"liveness_min": result.threshold},
        )
        state = StepState.SUCCEEDED if result.passed else StepState.NEGATIVE
        session = _advance(session, step_id, provider, state, evidence)
        steps[step_id] = str(state)
        evidences.append(evidence)
        self._c.sessions.append_audit_event(
            chain.append(
                EventType.STEP_COMPLETED,
                actor=command.principal,
                attributes={"step_id": step_id, **result.audit_summary()},
            )
        )
        return result, session

    def _run_face_match(
        self,
        tenant_id: TenantId,
        session: OnboardingSession,
        reference: ObjectRef,
        candidate: ObjectRef,
        steps: dict[str, str],
        evidences: list[Evidence],
        chain: AuditChain,
        command: SubmitSelfieCommand,
    ) -> tuple[float, bool, bool, OnboardingSession]:
        step_id = _find_step(session, Capability.BIOMETRICS_FACEMATCH)
        threshold = self._c.settings.face_match_min_similarity
        grey_low = self._c.settings.face_match_grey_band_low
        result = self._c.face_match.compare(tenant_id, reference, candidate, threshold=threshold)
        grey_band = grey_low <= result.similarity < threshold
        if step_id is None:
            return result.similarity, result.matched, grey_band, session

        provider = ProviderRef(result.provider_id, result.model_version)
        verdict = Verdict.PASS if result.matched else (
            Verdict.INCONCLUSIVE if grey_band else Verdict.FAIL
        )
        evidence = Evidence.create(
            step_id=step_id,
            kind=EvidenceKind.FACE_MATCH,
            provider=provider,
            verdict=verdict,
            scores={
                "similarity": result.similarity,
                "quality_candidate": result.quality_candidate,
                "quality_reference": result.quality_reference,
            },
            thresholds={"face_match_min": threshold, "grey_band_low": grey_low},
        )
        state = (
            StepState.SUCCEEDED
            if result.matched
            else (StepState.INCONCLUSIVE if grey_band else StepState.NEGATIVE)
        )
        session = _advance(session, step_id, provider, state, evidence)
        steps[step_id] = str(state)
        evidences.append(evidence)
        self._c.sessions.append_audit_event(
            chain.append(
                EventType.STEP_COMPLETED,
                actor=command.principal,
                attributes={"step_id": step_id, "grey_band": grey_band, **result.audit_summary()},
            )
        )
        return result.similarity, result.matched, grey_band, session


def _find_step(session: OnboardingSession, capability: Capability) -> str | None:
    for step in session.steps:
        if step.capability is capability and not step.is_terminal:
            return step.step_id
    return None


def _advance(
    session: OnboardingSession,
    step_id: str,
    provider: ProviderRef,
    state: StepState,
    evidence: Evidence | None,
) -> OnboardingSession:
    if not session.can_run(step_id):
        return session
    return session.start_step(step_id, provider).complete_step(
        step_id, state=state, evidence=evidence
    )


def _scoped_key(tenant_id: TenantId, key: str) -> str:
    prefix = f"tenants/{tenant_id.value}/"
    cleaned = key.lstrip("/")
    return cleaned if cleaned.startswith(prefix) else prefix + cleaned


__all__ = ["ArtifactSlot", "SubmitSelfie", "SubmitSelfieCommand", "SubmitSelfieResult"]
