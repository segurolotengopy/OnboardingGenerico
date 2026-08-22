"""Caso de uso: registrar y procesar una imagen de documento.

Ejecuta la cadena alineación → OCR → MRZ → validación cruzada y sella una
evidencia por paso. Puntos que conviene explicitar:

- El artefacto se registra por **referencia**, con su sha256 verificado antes
  de que ningún paso lo consuma (invariante I6).
- La MRZ es opcional: no todos los documentos LATAM presentan una legible. Si
  falta, el paso se marca `SKIPPED`, no `FAILED`.
- La validación cruzada MRZ ↔ OCR produce una evidencia con el **número** de
  discrepancias por campo, nunca los valores: el expediente de auditoría no
  puede llevar PII en claro.
- Los datos de identidad extraídos se persisten **cifrados** con el
  `tenant_id` como AAD.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from ..domain.enums import (
    ArtifactSlot,
    Capability,
    DataClass,
    EventType,
    EvidenceKind,
    StepState,
    Verdict,
)
from ..domain.events import AuditChain
from ..domain.identity import IdentityClaimSet
from ..domain.mrz import MrzCrossCheckResult, cross_check
from ..domain.session import OnboardingSession
from ..domain.value_objects import (
    Artifact,
    Evidence,
    ObjectRef,
    ProviderRef,
    SessionId,
    TenantId,
    utc_now,
)
from ..errors import MrzParseError, ProviderError, ValidationError
from ..observability import correlation_scope, get_logger

if TYPE_CHECKING:  # pragma: no cover
    from ..container import Container

_logger = get_logger("application.submit_document")

#: Esquema de extracción estructurada. El adaptador del LLM valida contra él y
#: lanza `ProviderContractViolationError` si la respuesta no encaja.
IDENTITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "id_number": {"type": "string"},
        "birth_date": {"type": "string", "format": "date"},
        "expiry_date": {"type": "string", "format": "date"},
        "issuing_state": {"type": "string"},
        "nationality": {"type": "string"},
        "sex": {"type": "string", "enum": ["M", "F", "X"]},
        "document_type": {"type": "string"},
    },
    "required": ["first_name", "last_name", "id_number", "birth_date"],
}


@dataclass(frozen=True, slots=True)
class SubmitDocumentCommand:
    """Petición de procesamiento de una cara del documento."""

    tenant_id: str
    session_id: str
    slot: str
    object_key: str
    sha256: str
    content_type: str = "image/jpeg"
    size_bytes: int = 0
    principal: str = "svc-requester"
    correlation_id: str | None = None
    expected_mrz_format: str | None = None


@dataclass(frozen=True, slots=True)
class SubmitDocumentResult:
    """Resultado del procesamiento, sin PII."""

    session_id: str
    state: str
    slot: str
    steps: Mapping[str, str]
    mrz_valid: bool | None
    mrz_failed_checks: tuple[str, ...]
    discrepancies: tuple[str, ...]
    minor_discrepancies: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    recapture_required: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "slot": self.slot,
            "steps": dict(self.steps),
            "mrz": {
                "valid": self.mrz_valid,
                "failed_checks": list(self.mrz_failed_checks),
            },
            "cross_check": {
                "discrepancies": list(self.discrepancies),
                "minor_discrepancies": list(self.minor_discrepancies),
            },
            "evidence_ids": list(self.evidence_ids),
            "recapture_required": self.recapture_required,
        }


class SubmitDocument:
    """Registra el artefacto y ejecuta los pasos documentales."""

    __slots__ = ("_c",)

    #: Umbrales por defecto de calidad de captura.
    DEFAULT_QUALITY = {"min_sharpness": 0.55, "max_glare": 0.30, "min_resolution_px": 1000}

    def __init__(self, container: Container) -> None:
        self._c = container

    def execute(self, command: SubmitDocumentCommand) -> SubmitDocumentResult:
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
            slot = _coerce_slot(command.slot)
            ref = self._register_artifact(tenant_id, session, slot, command)
            session = self._c.sessions.get(tenant_id, session_id)

            chain = AuditChain(
                tenant_id.value, session_id.value, self._c.sessions.audit_trail(tenant_id, session_id)
            )
            self._c.sessions.append_audit_event(
                chain.append(
                    EventType.ARTIFACT_REGISTERED,
                    actor=command.principal,
                    attributes={"slot": str(slot), "size_bytes": command.size_bytes},
                )
            )

            steps: dict[str, str] = {}
            evidences: list[Evidence] = []

            aligned_ref, session, recapture = self._run_alignment(
                tenant_id, session, ref, steps, evidences, chain, command
            )
            if recapture:
                self._persist(session, chain)
                return self._result(session, slot, steps, None, (), (), (), True)

            text, session = self._run_ocr(
                tenant_id, session, aligned_ref, steps, evidences, chain, command
            )
            claims, session = self._run_extraction(
                tenant_id, session, aligned_ref, text, steps, evidences, chain, command
            )
            mrz_result, session = self._run_mrz(
                tenant_id, session, aligned_ref, claims, steps, evidences, chain, command
            )
            session = self._run_cross_field(
                session, mrz_result, claims, steps, evidences, chain, command
            )

            self._persist(session, chain)
            return self._result(
                session,
                slot,
                steps,
                mrz_result.mrz_valid if mrz_result else None,
                mrz_result.failed_check_digits if mrz_result else (),
                mrz_result.discrepancies if mrz_result else (),
                mrz_result.minor_discrepancies if mrz_result else (),
                False,
                evidences,
            )

    # -- Pasos -------------------------------------------------------------

    def _register_artifact(
        self,
        tenant_id: TenantId,
        session: OnboardingSession,
        slot: ArtifactSlot,
        command: SubmitDocumentCommand,
    ) -> ObjectRef:
        ref = ObjectRef.build(
            scheme=self._scheme(),
            bucket=self._c.settings.artifact_bucket,
            key=self._scoped_key(tenant_id, command.object_key),
            sha256=command.sha256,
            size_bytes=command.size_bytes,
            content_type=command.content_type,
        )
        if not self._c.storage.exists(tenant_id, ref):
            raise ValidationError(
                "el objeto no está en el almacén: cárguelo con la URL prefirmada antes de registrarlo",
                field="object_key",
            )
        # I6: se verifica el sha256 antes de que ningún paso consuma el objeto.
        self._c.storage.get(tenant_id, ref)
        artifact = Artifact(slot=slot, ref=ref, data_class=DataClass.DOCUMENT, captured_at=utc_now())
        updated = session.register_artifact(artifact)
        self._c.sessions.save(updated, expected_version=session.version)
        return ref

    def _run_alignment(
        self,
        tenant_id: TenantId,
        session: OnboardingSession,
        ref: ObjectRef,
        steps: dict[str, str],
        evidences: list[Evidence],
        chain: AuditChain,
        command: SubmitDocumentCommand,
    ) -> tuple[ObjectRef, OnboardingSession, bool]:
        step_id = self._find_step(session, Capability.DOCUMENT_ALIGNMENT)
        page = "FRONT" if command.slot == str(ArtifactSlot.DOC_FRONT) else "BACK"
        result = self._c.alignment.align(tenant_id, ref, page=page)
        meets = result.meets(
            min_sharpness=float(self.DEFAULT_QUALITY["min_sharpness"]),
            max_glare=float(self.DEFAULT_QUALITY["max_glare"]),
            min_resolution_px=int(self.DEFAULT_QUALITY["min_resolution_px"]),
        )
        if step_id is None:
            return result.aligned, session, not meets

        evidence = Evidence.create(
            step_id=step_id,
            kind=EvidenceKind.DOCUMENT_ALIGNMENT,
            provider=ProviderRef(result.provider_id),
            verdict=Verdict.PASS if meets else Verdict.FAIL,
            scores={
                "sharpness": result.sharpness,
                "glare": result.glare,
                "resolution_px": float(result.resolution_px),
            },
            thresholds={k: float(v) for k, v in self.DEFAULT_QUALITY.items()},
        )
        state = StepState.SUCCEEDED if meets else StepState.NEGATIVE
        session = self._advance(session, step_id, ProviderRef(result.provider_id), state, evidence)
        steps[step_id] = str(state)
        evidences.append(evidence)
        self._audit_step(chain, command, step_id, evidence)
        return result.aligned, session, not meets

    def _run_ocr(
        self,
        tenant_id: TenantId,
        session: OnboardingSession,
        ref: ObjectRef,
        steps: dict[str, str],
        evidences: list[Evidence],
        chain: AuditChain,
        command: SubmitDocumentCommand,
    ) -> tuple[str, OnboardingSession]:
        step_id = self._find_step(session, Capability.OCR_DOCUMENT)
        chain_of_providers = self._c.capabilities.resolve_provider(
            tenant_id,
            Capability.OCR_DOCUMENT,
            country=session.country,
            document_type=str(session.document_type),
        )
        provider = chain_of_providers[0] if chain_of_providers else ProviderRef("unknown")

        page = "FRONT" if command.slot == str(ArtifactSlot.DOC_FRONT) else "BACK"
        try:
            ocr_result = self._c.ocr.detect_text(tenant_id, ref, page=page)
        except ProviderError as exc:
            # La cadena de reserva se activa arriba, en el dispatcher; aquí se
            # deja constancia del fallo con su código estable.
            if step_id is not None:
                session = self._advance(
                    session, step_id, provider, StepState.FAILED, None, error_code=exc.code
                )
                steps[step_id] = str(StepState.FAILED)
            raise

        min_confidence = ocr_result.min_confidence
        threshold = self._c.settings.ocr_min_field_confidence

        if step_id is not None:
            evidence = Evidence.create(
                step_id=step_id,
                kind=EvidenceKind.OCR,
                provider=provider,
                verdict=Verdict.PASS if min_confidence >= threshold else Verdict.INCONCLUSIVE,
                scores={
                    "min_field_confidence": min_confidence,
                    "block_count": float(len(ocr_result.blocks)),
                },
                thresholds={"min_field_confidence": threshold},
            )
            state = (
                StepState.SUCCEEDED if min_confidence >= threshold else StepState.INCONCLUSIVE
            )
            session = self._advance(session, step_id, provider, state, evidence)
            steps[step_id] = str(state)
            evidences.append(evidence)
            self._audit_step(chain, command, step_id, evidence)

        # El texto del OCR es PII: se guarda cifrado y no se registra.
        self._store_claims(tenant_id, session.session_id, {"raw_text": ocr_result.text})
        return ocr_result.text, session

    def _run_extraction(
        self,
        tenant_id: TenantId,
        session: OnboardingSession,
        ref: ObjectRef,
        text: str,
        steps: dict[str, str],
        evidences: list[Evidence],
        chain: AuditChain,
        command: SubmitDocumentCommand,
    ) -> tuple[IdentityClaimSet, OnboardingSession]:
        """Extracción estructurada con LLM multimodal.

        Es el patrón portable: los procesadores de identidad de ambas nubes
        cubren esencialmente EE. UU., así que la semántica por país la aporta
        el LLM, que sí tiene paridad total entre AWS y GCP.
        """
        step_id = self._find_step(session, Capability.EXTRACTION_SEMANTIC)
        if step_id is None:
            return IdentityClaimSet.create(source="ocr"), session

        template = f"{session.country}/{session.document_type}"
        provider = ProviderRef("claude_primary", "1.0.0")
        result = self._c.llm.extract_structured(
            tenant_id,
            prompt=f"Extraiga los campos de identidad del documento.\n{text}",
            schema=IDENTITY_SCHEMA,
            image_refs=(ref,),
            template=template,
        )
        claims = IdentityClaimSet.from_mapping(dict(result.data), source="llm")
        threshold = self._c.settings.ocr_min_field_confidence
        evidence = Evidence.create(
            step_id=step_id,
            kind=EvidenceKind.SEMANTIC_EXTRACTION,
            provider=provider,
            verdict=(
                Verdict.PASS if result.min_field_confidence >= threshold else Verdict.INCONCLUSIVE
            ),
            scores={"min_field_confidence": result.min_field_confidence},
            thresholds={"min_field_confidence": threshold},
        )
        state = (
            StepState.SUCCEEDED
            if result.min_field_confidence >= threshold
            else StepState.INCONCLUSIVE
        )
        session = self._advance(session, step_id, provider, state, evidence)
        steps[step_id] = str(state)
        evidences.append(evidence)
        self._audit_step(chain, command, step_id, evidence, extra=result.audit_summary())
        self._store_claims(tenant_id, session.session_id, claims.as_dict())
        return claims, session

    def _run_mrz(
        self,
        tenant_id: TenantId,
        session: OnboardingSession,
        ref: ObjectRef,
        claims: IdentityClaimSet,
        steps: dict[str, str],
        evidences: list[Evidence],
        chain: AuditChain,
        command: SubmitDocumentCommand,
    ) -> tuple[MrzCrossCheckResult | None, OnboardingSession]:
        step_id = self._find_step(session, Capability.MRZ_PARSE)
        if step_id is None:
            return None, session
        provider = ProviderRef("local_mrz", "1.0.0")
        try:
            record = self._c.mrz.read(tenant_id, ref)
        except MrzParseError:
            # No todos los documentos LATAM llevan MRZ legible: es SKIPPED,
            # no FAILED. Marcarlo como fallo dispararía reintentos inútiles.
            session = self._advance(session, step_id, provider, StepState.SKIPPED, None)
            steps[step_id] = str(StepState.SKIPPED)
            return None, session

        result = cross_check(record, claims)
        evidence = Evidence.create(
            step_id=step_id,
            kind=EvidenceKind.MRZ,
            provider=provider,
            verdict=Verdict.PASS if record.is_valid else Verdict.FAIL,
            scores={
                "checks_passed": float(sum(1 for ok in record.check_results.values() if ok)),
                "checks_failed": float(len(record.failed_checks)),
            },
        )
        state = StepState.SUCCEEDED if record.is_valid else StepState.NEGATIVE
        session = self._advance(session, step_id, provider, state, evidence)
        steps[step_id] = str(state)
        evidences.append(evidence)
        self._audit_step(chain, command, step_id, evidence, extra=record.audit_summary())

        self._store_claims(tenant_id, session.session_id, record.to_claims().as_dict())
        return result, session

    def _run_cross_field(
        self,
        session: OnboardingSession,
        mrz_result: MrzCrossCheckResult | None,
        claims: IdentityClaimSet,
        steps: dict[str, str],
        evidences: list[Evidence],
        chain: AuditChain,
        command: SubmitDocumentCommand,
    ) -> OnboardingSession:
        step_id = self._find_step(session, Capability.VALIDATION_CROSSFIELD)
        if step_id is None or mrz_result is None:
            return session
        provider = ProviderRef("internal_crossfield", "1.0.0")
        evidence = Evidence.create(
            step_id=step_id,
            kind=EvidenceKind.CROSS_FIELD,
            provider=provider,
            verdict=Verdict.PASS if mrz_result.is_consistent else Verdict.FAIL,
            scores={
                "discrepancies": float(len(mrz_result.discrepancies)),
                "minor_discrepancies": float(len(mrz_result.minor_discrepancies)),
            },
            thresholds={"max_discrepancies": 0.0},
        )
        state = StepState.SUCCEEDED if mrz_result.is_consistent else StepState.NEGATIVE
        session = self._advance(session, step_id, provider, state, evidence)
        steps[step_id] = str(state)
        evidences.append(evidence)
        self._audit_step(chain, command, step_id, evidence, extra=mrz_result.as_dict())
        return session

    # -- Auxiliares --------------------------------------------------------

    def _advance(
        self,
        session: OnboardingSession,
        step_id: str,
        provider: ProviderRef,
        state: StepState,
        evidence: Evidence | None,
        *,
        error_code: str | None = None,
    ) -> OnboardingSession:
        if not session.can_run(step_id):
            return session
        running = session.start_step(step_id, provider)
        return running.complete_step(
            step_id, state=state, evidence=evidence, error_code=error_code
        )

    def _persist(self, session: OnboardingSession, chain: AuditChain) -> None:
        """Persiste el agregado tras la cadena de pasos.

        No se pasa `expected_version` porque el agregado ya avanzó varias
        versiones en memoria durante esta unidad de trabajo; el bloqueo
        optimista se aplicó al registrar el artefacto, que es el punto donde
        dos escritores concurrentes pueden colisionar.
        """
        self._c.sessions.save(session, expected_version=None)

    def _audit_step(
        self,
        chain: AuditChain,
        command: SubmitDocumentCommand,
        step_id: str,
        evidence: Evidence,
        *,
        extra: Mapping[str, Any] | None = None,
    ) -> None:
        attributes: dict[str, Any] = {
            "step_id": step_id,
            "evidence_id": evidence.evidence_id,
            "verdict": str(evidence.verdict),
            "provider": str(evidence.provider),
        }
        if extra:
            attributes.update(dict(extra))
        self._c.sessions.append_audit_event(
            chain.append(EventType.STEP_COMPLETED, actor=command.principal, attributes=attributes)
        )

    def _store_claims(self, tenant_id: TenantId, session_id: SessionId, data: Mapping[str, Any]) -> None:
        """Persiste atributos de identidad **cifrados** con el AAD del tenant."""
        encrypted = self._c.cipher.encrypt_item(tenant_id, dict(data))
        self._c.idempotency.record_result(
            tenant_id, "claims", session_id.value, {"encrypted": encrypted}
        )

    @staticmethod
    def _find_step(session: OnboardingSession, capability: Capability) -> str | None:
        for step in session.steps:
            if step.capability is capability and not step.is_terminal:
                return step.step_id
        return None

    def _scheme(self) -> str:
        return {"aws": "s3", "gcp": "gs"}.get(self._c.settings.cloud_provider, "mem")

    @staticmethod
    def _scoped_key(tenant_id: TenantId, key: str) -> str:
        prefix = f"tenants/{tenant_id.value}/"
        cleaned = key.lstrip("/")
        return cleaned if cleaned.startswith(prefix) else prefix + cleaned

    @staticmethod
    def _result(
        session: OnboardingSession,
        slot: ArtifactSlot,
        steps: Mapping[str, str],
        mrz_valid: bool | None,
        failed_checks: tuple[str, ...],
        discrepancies: tuple[str, ...],
        minor: tuple[str, ...],
        recapture: bool,
        evidences: list[Evidence] | None = None,
    ) -> SubmitDocumentResult:
        return SubmitDocumentResult(
            session_id=session.session_id.value,
            state=str(session.state),
            slot=str(slot),
            steps=dict(steps),
            mrz_valid=mrz_valid,
            mrz_failed_checks=failed_checks,
            discrepancies=discrepancies,
            minor_discrepancies=minor,
            evidence_ids=tuple(e.evidence_id for e in (evidences or ())),
            recapture_required=recapture,
        )


def _coerce_slot(value: str) -> ArtifactSlot:
    try:
        return ArtifactSlot(value.strip().upper())
    except ValueError as exc:
        known = ", ".join(sorted(s.value for s in ArtifactSlot))
        raise ValidationError(
            f"ranura de artefacto desconocida '{value}'; admitidas: {known}", field="slot"
        ) from exc


__all__ = ["SubmitDocument", "SubmitDocumentCommand", "SubmitDocumentResult"]
