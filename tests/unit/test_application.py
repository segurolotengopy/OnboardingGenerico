"""Pruebas de los casos de uso contra los adaptadores en memoria."""

from __future__ import annotations

from typing import Any

import pytest

from onboarding_generico.application import (
    AssignCaseCommand,
    HandleManualReview,
    PurgeCommand,
    PurgeTenantData,
    ResolveCaseCommand,
    ResolveDecision,
    ResolveDecisionCommand,
    StartSession,
    StartSessionCommand,
    SubmitDocument,
    SubmitDocumentCommand,
    SubmitSelfie,
    SubmitSelfieCommand,
)
from onboarding_generico.container import Container
from onboarding_generico.domain.enums import DecisionOutcome, SessionState, StepState
from onboarding_generico.domain.events import verify_chain
from onboarding_generico.domain.value_objects import SessionId, TenantId
from onboarding_generico.errors import (
    AuthorizationError,
    CapabilityNotProvisionedError,
    DomainError,
    NoApplicableFlowSpecError,
    ValidationError,
)

#: Principal autorizado por `provision_demo_tenant` en el contenedor de prueba.
TEST_PRINCIPAL = "svc-requester"

#: Ejemplo canónico ICAO TD1 (ERIKSSON ANNA MARIA).
TD1_CANONICAL = (
    "I<UTOD231458907<<<<<<<<<<<<<<<\n7408122F1204159UTO<<<<<<<<<<<6\nERIKSSON<<ANNA<MARIA<<<<<<<<<<"
)

CLAIMS = {
    "first_name": "ANNA MARIA",
    "last_name": "ERIKSSON",
    "id_number": "D23145890",
    "birth_date": "1974-08-12",
    "expiry_date": "2012-04-15",
    "issuing_state": "UTO",
    "nationality": "UTO",
    "sex": "F",
}


# --------------------------------------------------------------------------
# Ayudantes
# --------------------------------------------------------------------------


def _start(container: Container, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "tenant_id": "acme",
        "subject_ref": "subj-1",
        "country": "MX",
        "document_type": "INE_2019",
        "principal": TEST_PRINCIPAL,
    }
    arguments.update(overrides)
    return StartSession(container).execute(StartSessionCommand(**arguments))


def _submit_document(
    container: Container,
    tenant: TenantId,
    upload: Any,
    session_id: str,
    *,
    mrz_text: str = TD1_CANONICAL,
    claims: dict[str, Any] | None = None,
) -> Any:
    key = f"sessions/{session_id}/DOC_FRONT"
    ref, digest, size = upload(container, tenant, key, b"imagen-frontal")
    container.ocr.script(ref, mrz_text)
    container.mrz.script(ref, mrz_text)
    container.llm.script("MX/INE_2019", dict(claims if claims is not None else CLAIMS))
    return SubmitDocument(container).execute(
        SubmitDocumentCommand(
            tenant_id=tenant.value,
            session_id=session_id,
            slot="DOC_FRONT",
            object_key=key,
            sha256=digest,
            size_bytes=size,
            principal=TEST_PRINCIPAL,
        )
    )


def _submit_selfie(
    container: Container,
    tenant: TenantId,
    upload: Any,
    session_id: str,
    *,
    liveness_score: float = 0.97,
    injection: bool = False,
    similarity: float = 0.93,
) -> Any:
    key = f"sessions/{session_id}/SELFIE"
    ref, digest, size = upload(container, tenant, key, b"selfie")
    liveness_session = container.liveness.create_session(tenant)
    container.liveness.script(
        liveness_session.provider_session_id,
        score=liveness_score,
        injection_detected=injection,
        audited_image=ref,
    )
    container.face_match.script(ref, ref, similarity)
    return SubmitSelfie(container).execute(
        SubmitSelfieCommand(
            tenant_id=tenant.value,
            session_id=session_id,
            object_key=key,
            sha256=digest,
            size_bytes=size,
            liveness_session_id=liveness_session.provider_session_id,
            principal=TEST_PRINCIPAL,
        )
    )


def _to_processing(container: Container, tenant: TenantId, session_id: str) -> None:
    session = container.sessions.get(tenant, SessionId(session_id))
    container.sessions.save(session.transition_to(SessionState.PROCESSING))


# --------------------------------------------------------------------------
# StartSession
# --------------------------------------------------------------------------


def test_start_session_resolves_freezes_and_emits_upload_targets(container: Container) -> None:
    result = _start(container)
    assert result.state == "CREATED"
    assert result.spec_key == "GLOBAL:Standard-eKYC-Latam"
    assert result.spec_hash.startswith("sha256:")
    slots = {target.slot for target in result.upload_targets}
    assert slots == {"DOC_FRONT", "DOC_BACK", "SELFIE"}
    assert all("token=" in target.url for target in result.upload_targets)


def test_start_session_freezes_the_spec_reference(container: Container) -> None:
    """Una republicación posterior no puede afectar a una sesión en vuelo."""
    result = _start(container)
    session = container.sessions.get(TenantId("acme"), SessionId(result.session_id))
    assert session.spec_ref.content_hash == result.spec_hash
    assert session.spec_ref.version == "1.0.0"


def test_start_session_requires_authorization(container: Container) -> None:
    with pytest.raises(AuthorizationError):
        _start(container, principal="intruso")


def test_start_session_rejects_unknown_country(container: Container) -> None:
    with pytest.raises(NoApplicableFlowSpecError):
        _start(container, country="FR")


def test_start_session_rejects_unknown_document_type(container: Container) -> None:
    with pytest.raises(ValidationError):
        _start(container, document_type="CEDULA_MARCIANA")


def test_start_session_fails_when_capability_is_not_provisioned(
    container: Container, tenant: TenantId
) -> None:
    other = TenantId("globex")
    container.config.register_tenant(other)
    container.authorization.grant(TEST_PRINCIPAL, other, "*")
    with pytest.raises(CapabilityNotProvisionedError) as excinfo:
        StartSession(container).execute(
            StartSessionCommand(
                tenant_id=other.value,
                subject_ref="s",
                country="MX",
                document_type="INE_2019",
                principal=TEST_PRINCIPAL,
            )
        )
    assert excinfo.value.details["missing_capabilities"]


def test_start_session_opens_the_audit_chain(container: Container, tenant: TenantId) -> None:
    result = _start(container)
    trail = container.sessions.audit_trail(tenant, SessionId(result.session_id))
    assert len(trail) == 1
    assert str(trail[0].event_type) == "SESSION_CREATED"
    verify_chain(trail)


# --------------------------------------------------------------------------
# SubmitDocument
# --------------------------------------------------------------------------


def test_submit_document_runs_the_document_pipeline(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    session_id = _start(container).session_id
    result = _submit_document(container, tenant, upload, session_id)
    assert result.recapture_required is False
    assert result.steps["document_alignment"] == "SUCCEEDED"
    assert result.steps["data_extraction_ocr"] == "SUCCEEDED"
    assert result.steps["semantic_extraction"] == "SUCCEEDED"
    assert result.steps["mrz_parse"] == "SUCCEEDED"
    assert result.mrz_valid is True
    assert result.discrepancies == ()
    assert len(result.evidence_ids) == 5


def test_submit_document_detects_cross_field_discrepancy(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    """La MRZ dice una cosa y el LLM otra: se marca, no se decide aquí."""
    session_id = _start(container).session_id
    divergent = dict(CLAIMS, birth_date="1980-01-01")
    result = _submit_document(container, tenant, upload, session_id, claims=divergent)
    assert "birth_date" in result.discrepancies
    assert result.steps["cross_field_validation"] == "NEGATIVE"


def test_submit_document_reports_bad_mrz_check_digits(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    session_id = _start(container).session_id
    corrupted = TD1_CANONICAL.replace("D231458907", "D231458908")
    result = _submit_document(container, tenant, upload, session_id, mrz_text=corrupted)
    assert result.mrz_valid is False
    assert "document_number" in result.mrz_failed_checks
    assert result.steps["mrz_parse"] == "NEGATIVE"


def test_submit_document_rejects_unknown_object(container: Container) -> None:
    session_id = _start(container).session_id
    with pytest.raises(ValidationError):
        SubmitDocument(container).execute(
            SubmitDocumentCommand(
                tenant_id="acme",
                session_id=session_id,
                slot="DOC_FRONT",
                object_key="sessions/x/DOC_FRONT",
                sha256="a" * 64,
                principal=TEST_PRINCIPAL,
            )
        )


def test_submit_document_rejects_unknown_slot(container: Container) -> None:
    session_id = _start(container).session_id
    with pytest.raises(ValidationError):
        SubmitDocument(container).execute(
            SubmitDocumentCommand(
                tenant_id="acme",
                session_id=session_id,
                slot="DOC_LATERAL",
                object_key="k",
                sha256="a" * 64,
                principal=TEST_PRINCIPAL,
            )
        )


def test_submit_document_requests_recapture_on_poor_quality(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    from onboarding_generico.ports.imaging import AlignmentResult

    session_id = _start(container).session_id
    key = f"sessions/{session_id}/DOC_FRONT"
    ref, digest, size = upload(container, tenant, key, b"imagen-borrosa")
    container.alignment.script(
        ref,
        AlignmentResult(aligned=ref, detected=True, sharpness=0.10, glare=0.80, resolution_px=300),
    )
    result = SubmitDocument(container).execute(
        SubmitDocumentCommand(
            tenant_id=tenant.value,
            session_id=session_id,
            slot="DOC_FRONT",
            object_key=key,
            sha256=digest,
            size_bytes=size,
            principal=TEST_PRINCIPAL,
        )
    )
    assert result.recapture_required is True
    assert result.steps["document_alignment"] == "NEGATIVE"


def test_submit_document_stores_claims_encrypted(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    """Los atributos de identidad se persisten cifrados con el AAD del tenant."""
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    stored = container.idempotency.result_for(tenant, "claims", session_id)
    assert stored is not None
    assert "D23145890" not in str(stored)
    decrypted = container.cipher.decrypt_item(tenant, dict(stored["encrypted"]))
    assert decrypted["id_number"] == "D23145890"


def test_submit_document_keeps_the_audit_chain_intact(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    trail = container.sessions.audit_trail(tenant, SessionId(session_id))
    verify_chain(trail)
    assert len(trail) >= 6
    assert "ERIKSSON" not in str([event.attributes for event in trail])


# --------------------------------------------------------------------------
# SubmitSelfie
# --------------------------------------------------------------------------


def test_submit_selfie_runs_liveness_then_face_match(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    result = _submit_selfie(container, tenant, upload, session_id)
    assert result.liveness_passed is True
    assert result.matched is True
    assert result.grey_band is False
    assert result.steps["liveness_check"] == "SUCCEEDED"
    assert result.steps["biometric_matching"] == "SUCCEEDED"


def test_failed_liveness_skips_face_match(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    """Comparar contra una presentación de ataque produce datos engañosos."""
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    result = _submit_selfie(container, tenant, upload, session_id, liveness_score=0.20)
    assert result.liveness_passed is False
    assert "biometric_matching" not in result.steps
    assert result.similarity == 0.0


def test_injection_detected_fails_liveness_even_with_high_score(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    result = _submit_selfie(
        container, tenant, upload, session_id, liveness_score=0.99, injection=True
    )
    assert result.injection_detected is True
    assert result.liveness_passed is False


def test_grey_band_similarity_is_inconclusive(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    result = _submit_selfie(container, tenant, upload, session_id, similarity=0.78)
    assert result.grey_band is True
    assert result.matched is False
    assert result.steps["biometric_matching"] == str(StepState.INCONCLUSIVE)


def test_selfie_artifact_has_purge_date(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    from onboarding_generico.domain.enums import ArtifactSlot

    session_id = _start(container).session_id
    _submit_selfie(container, tenant, upload, session_id)
    session = container.sessions.get(tenant, SessionId(session_id))
    selfie = session.artifact(ArtifactSlot.SELFIE)
    assert selfie is not None
    assert selfie.purgeable_from is not None


# --------------------------------------------------------------------------
# ResolveDecision
# --------------------------------------------------------------------------


def test_decision_on_a_clean_case(container: Container, tenant: TenantId, upload: Any) -> None:
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    _submit_selfie(container, tenant, upload, session_id)
    _to_processing(container, tenant, session_id)

    result = ResolveDecision(container).execute(
        ResolveDecisionCommand(
            tenant_id=tenant.value, session_id=session_id, principal=TEST_PRINCIPAL
        )
    )
    # El tenant está configurado como SIGNALS_ONLY por defecto.
    assert result.outcome == str(DecisionOutcome.SIGNALS_ONLY)
    assert result.issuer == "SIGNALS_ONLY"
    assert result.state == str(SessionState.RETAINED)
    assert result.evidence_manifest.startswith("sha256:")
    assert result.review_case_id is None


def test_decision_opens_a_review_case_on_grey_band(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    _submit_selfie(container, tenant, upload, session_id, similarity=0.78)
    _to_processing(container, tenant, session_id)

    result = ResolveDecision(container).execute(
        ResolveDecisionCommand(
            tenant_id=tenant.value, session_id=session_id, principal=TEST_PRINCIPAL
        )
    )
    assert result.review_case_id is not None
    assert result.state == str(SessionState.PENDING_REVIEW)
    assert "FACE_GREY_BAND" in [r["code"] for r in result.reasons]


def test_decision_publishes_an_integration_event(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    _submit_selfie(container, tenant, upload, session_id)
    _to_processing(container, tenant, session_id)
    ResolveDecision(container).execute(
        ResolveDecisionCommand(
            tenant_id=tenant.value, session_id=session_id, principal=TEST_PRINCIPAL
        )
    )
    events = container.events.published_for(tenant, session_id)
    assert len(events) == 1
    assert events[0].event_type == "og.session.decided"
    assert events[0].ordering_key == f"{tenant.value}/{session_id}"


def test_only_one_decision_per_session(container: Container, tenant: TenantId, upload: Any) -> None:
    """Invariante I5: una segunda decisión exige re-verificación."""
    session_id = _start(container).session_id
    _submit_selfie(container, tenant, upload, session_id)
    _to_processing(container, tenant, session_id)
    command = ResolveDecisionCommand(
        tenant_id=tenant.value, session_id=session_id, principal=TEST_PRINCIPAL
    )
    ResolveDecision(container).execute(command)
    with pytest.raises(DomainError):
        ResolveDecision(container).execute(command)


def test_decision_requires_an_intact_audit_chain(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    from dataclasses import replace

    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    _to_processing(container, tenant, session_id)

    trail = container.sessions.audit_trail(tenant, SessionId(session_id))
    tampered = replace(trail[0], actor="atacante")
    container.sessions._audit[(tenant.value, session_id)][0] = tampered

    from onboarding_generico.errors import AuditChainError

    with pytest.raises(AuditChainError):
        ResolveDecision(container).execute(
            ResolveDecisionCommand(
                tenant_id=tenant.value, session_id=session_id, principal=TEST_PRINCIPAL
            )
        )


# --------------------------------------------------------------------------
# Revisión humana
# --------------------------------------------------------------------------


def test_manual_review_assign_and_resolve(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    _submit_selfie(container, tenant, upload, session_id, similarity=0.78)
    _to_processing(container, tenant, session_id)
    ResolveDecision(container).execute(
        ResolveDecisionCommand(
            tenant_id=tenant.value, session_id=session_id, principal=TEST_PRINCIPAL
        )
    )

    review = HandleManualReview(container)
    container.authorization.grant(TEST_PRINCIPAL, tenant, ["review:read", "review:resolve"])
    case = review.assign_next(
        AssignCaseCommand(tenant_id=tenant.value, reviewer="ana", principal=TEST_PRINCIPAL)
    )
    assert case is not None
    assert case.state == "IN_REVIEW"
    assert case.assigned_to == "ana"
    assert "FACE_GREY_BAND" in case.reasons

    resolution = review.resolve(
        ResolveCaseCommand(
            tenant_id=tenant.value,
            case_id=case.case_id,
            reviewer="ana",
            outcome="APPROVED",
            principal=TEST_PRINCIPAL,
        )
    )
    assert resolution.outcome == "APPROVED"
    assert resolution.session_state == str(SessionState.RETAINED)
    assert review.queue_depth(tenant.value)["RESOLVED"] == 1


def test_reviewer_cannot_emit_signals_only(container: Container, tenant: TenantId) -> None:
    review = HandleManualReview(container)
    container.authorization.grant(TEST_PRINCIPAL, tenant, ["review:resolve"])
    with pytest.raises(ValidationError):
        review.resolve(
            ResolveCaseCommand(
                tenant_id=tenant.value,
                case_id="x",
                reviewer="ana",
                outcome="SIGNALS_ONLY",
                principal=TEST_PRINCIPAL,
            )
        )


def test_empty_queue_returns_none(container: Container, tenant: TenantId) -> None:
    container.authorization.grant(TEST_PRINCIPAL, tenant, ["review:read"])
    case = HandleManualReview(container).assign_next(
        AssignCaseCommand(tenant_id=tenant.value, reviewer="ana", principal=TEST_PRINCIPAL)
    )
    assert case is None


# --------------------------------------------------------------------------
# Purga
# --------------------------------------------------------------------------


def test_purge_removes_expired_sessions_and_keeps_the_audit_trail(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    from dataclasses import replace
    from datetime import timedelta

    session_id = _start(container).session_id
    _submit_document(container, tenant, upload, session_id)
    session = container.sessions.get(tenant, SessionId(session_id))
    expired = replace(
        session.transition_to(SessionState.EXPIRED),
        created_at=session.created_at - timedelta(days=30),
    )
    container.sessions.save(expired)

    result = PurgeTenantData(container).execute(
        PurgeCommand(tenant_id=tenant.value, principal=TEST_PRINCIPAL)
    )
    assert session_id in result.sessions_purged
    assert result.objects_deleted >= 1
    assert container.sessions.find(tenant, SessionId(session_id)) is None
    # La constancia de que la sesión existió y fue purgada sobrevive.
    trail = container.sessions.audit_trail(tenant, SessionId(session_id))
    assert any(str(event.event_type) == "PURGE_COMPLETED" for event in trail)
    verify_chain(trail)


def test_purge_skips_blocked_sessions(container: Container, tenant: TenantId, upload: Any) -> None:
    """`BLOCKED` es limitación del tratamiento (art. 18 GDPR), no borrado."""
    session_id = _start(container).session_id
    session = container.sessions.get(tenant, SessionId(session_id))
    blocked = (
        session.transition_to(SessionState.COLLECTING)
        .transition_to(SessionState.PROCESSING)
        .transition_to(SessionState.DECIDED)
        .seal()
        .block()
    )
    container.sessions.save(blocked)

    result = PurgeTenantData(container).execute(
        PurgeCommand(tenant_id=tenant.value, principal=TEST_PRINCIPAL)
    )
    assert session_id in result.skipped_blocked
    assert session_id not in result.sessions_purged
    assert container.sessions.find(tenant, SessionId(session_id)) is not None


def test_purge_dry_run_changes_nothing(container: Container, tenant: TenantId) -> None:
    from dataclasses import replace
    from datetime import timedelta

    session_id = _start(container).session_id
    session = container.sessions.get(tenant, SessionId(session_id))
    container.sessions.save(
        replace(
            session.transition_to(SessionState.CANCELLED),
            created_at=session.created_at - timedelta(days=30),
        )
    )
    result = PurgeTenantData(container).execute(
        PurgeCommand(tenant_id=tenant.value, principal=TEST_PRINCIPAL, dry_run=True)
    )
    assert result.dry_run is True
    assert session_id in result.sessions_purged
    assert container.sessions.find(tenant, SessionId(session_id)) is not None


def test_purge_with_shredding_destroys_the_tenant_key(
    container: Container, tenant: TenantId
) -> None:
    from onboarding_generico.errors import KeyDestroyedError

    encrypted = container.cipher.encrypt_item(tenant, {"id_number": "D23145890"})
    result = PurgeTenantData(container).execute(
        PurgeCommand(tenant_id=tenant.value, principal=TEST_PRINCIPAL, shred_tenant_key=True)
    )
    assert result.key_shredded is True
    with pytest.raises(KeyDestroyedError):
        container.cipher.decrypt_item(tenant, encrypted)


def test_purge_requires_authorization(container: Container, tenant: TenantId) -> None:
    with pytest.raises(AuthorizationError):
        PurgeTenantData(container).execute(
            PurgeCommand(tenant_id=tenant.value, principal="intruso")
        )


def test_purge_is_serialized_by_a_distributed_lock(container: Container, tenant: TenantId) -> None:
    from onboarding_generico.application.purge_tenant_data import PURGE_LOCK_RESOURCE
    from onboarding_generico.errors import LockAcquisitionError

    container.locks.acquire(tenant, PURGE_LOCK_RESOURCE, ttl_seconds=60)
    with pytest.raises(LockAcquisitionError):
        PurgeTenantData(container).execute(
            PurgeCommand(tenant_id=tenant.value, principal=TEST_PRINCIPAL)
        )


# --------------------------------------------------------------------------
# Aislamiento entre tenants
# --------------------------------------------------------------------------


def test_a_session_is_not_visible_from_another_tenant(
    container: Container, tenant: TenantId
) -> None:
    from onboarding_generico.errors import SessionNotFoundError

    session_id = _start(container).session_id
    other = TenantId("globex")
    assert container.sessions.find(other, SessionId(session_id)) is None
    with pytest.raises(SessionNotFoundError):
        container.sessions.get(other, SessionId(session_id))


def test_storage_rejects_cross_tenant_reference(
    container: Container, tenant: TenantId, upload: Any
) -> None:
    from onboarding_generico.errors import TenantIsolationError

    ref, _, _ = upload(container, tenant, "sessions/x/DOC_FRONT", b"datos")
    other = TenantId("globex")
    with pytest.raises(TenantIsolationError):
        container.storage.get(other, ref)
    assert container.storage.exists(other, ref) is False
