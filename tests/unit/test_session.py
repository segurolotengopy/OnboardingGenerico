"""Pruebas de la máquina de estados y las invariantes de la sesión."""

from __future__ import annotations

from datetime import timedelta

import pytest

from onboarding_generico.domain.enums import (
    ArtifactSlot,
    Capability,
    DataClass,
    DocumentType,
    EvidenceKind,
    SessionState,
    StepState,
    Verdict,
)
from onboarding_generico.domain.session import (
    ALLOWED_TRANSITIONS,
    TERMINAL_STATES,
    OnboardingSession,
    Step,
    build_selfie_artifact,
)
from onboarding_generico.domain.value_objects import (
    Artifact,
    Evidence,
    FlowSpecRef,
    ObjectRef,
    ProviderRef,
    SubjectRef,
    TenantId,
)
from onboarding_generico.errors import (
    DomainError,
    InvalidStateTransitionError,
    ValidationError,
)

SPEC_REF = FlowSpecRef(key="GLOBAL:demo", version="1.0.0", content_hash="sha256:" + "0" * 64)


def _ref(key: str = "tenants/acme/x") -> ObjectRef:
    return ObjectRef.build(scheme="mem", bucket="b", key=key, sha256="b" * 64)


def _session(steps: tuple[Step, ...] | None = None) -> OnboardingSession:
    return OnboardingSession.start(
        tenant_id=TenantId("acme"),
        subject=SubjectRef("subj-1"),
        country="MX",
        document_type=DocumentType.INE_2019,
        tier="IAL2",
        spec_ref=SPEC_REF,
        steps=steps
        or (
            Step(step_id="align", capability=Capability.DOCUMENT_ALIGNMENT),
            Step(step_id="ocr", capability=Capability.OCR_DOCUMENT, depends_on=("align",)),
        ),
        ttl_seconds=3600,
    )


# --------------------------------------------------------------------------
# Creación
# --------------------------------------------------------------------------


def test_start_sets_created_and_expiry() -> None:
    session = _session()
    assert session.state is SessionState.CREATED
    assert session.version == 1
    assert session.expires_at is not None
    assert session.expires_at - session.created_at == timedelta(seconds=3600)


def test_start_rejects_empty_steps() -> None:
    with pytest.raises(ValidationError):
        OnboardingSession.start(
            tenant_id=TenantId("acme"),
            subject=SubjectRef("s"),
            country="MX",
            document_type=DocumentType.INE_2019,
            tier="IAL2",
            spec_ref=SPEC_REF,
            steps=(),
            ttl_seconds=60,
        )


def test_start_rejects_cycles_and_dangling_dependencies() -> None:
    cyclic = (
        Step(step_id="a", capability=Capability.OCR_DOCUMENT, depends_on=("b",)),
        Step(step_id="b", capability=Capability.OCR_DOCUMENT, depends_on=("a",)),
    )
    with pytest.raises(ValidationError):
        _session(cyclic)

    dangling = (Step(step_id="a", capability=Capability.OCR_DOCUMENT, depends_on=("zz",)),)
    with pytest.raises(ValidationError):
        _session(dangling)


def test_start_rejects_duplicate_step_ids() -> None:
    duplicated = (
        Step(step_id="a", capability=Capability.OCR_DOCUMENT),
        Step(step_id="a", capability=Capability.MRZ_PARSE),
    )
    with pytest.raises(ValidationError):
        _session(duplicated)


# --------------------------------------------------------------------------
# Transiciones
# --------------------------------------------------------------------------


def test_valid_transition_bumps_version() -> None:
    session = _session().transition_to(SessionState.COLLECTING)
    assert session.state is SessionState.COLLECTING
    assert session.version == 2


def test_invalid_transition_raises_with_codes() -> None:
    session = _session()
    with pytest.raises(InvalidStateTransitionError) as excinfo:
        session.transition_to(SessionState.DECIDED)
    assert excinfo.value.code == "OG_INVALID_TRANSITION"
    assert excinfo.value.details["current_state"] == "CREATED"


def test_purged_is_absorbing() -> None:
    assert ALLOWED_TRANSITIONS[SessionState.PURGED] == frozenset()


def test_full_happy_path_to_retained() -> None:
    session = _session()
    session = session.transition_to(SessionState.COLLECTING)
    session = session.transition_to(SessionState.PROCESSING)
    session = session.transition_to(SessionState.DECIDED)
    session = session.seal()
    assert session.state is SessionState.RETAINED


def test_review_loop() -> None:
    session = _session().transition_to(SessionState.COLLECTING).transition_to(SessionState.PROCESSING)
    session = session.transition_to(SessionState.PENDING_REVIEW)
    session = session.transition_to(SessionState.IN_REVIEW)
    # El revisor puede devolver el caso a la cola.
    session = session.transition_to(SessionState.PENDING_REVIEW)
    session = session.transition_to(SessionState.IN_REVIEW)
    session = session.transition_to(SessionState.DECIDED)
    assert session.state is SessionState.DECIDED


def test_blocked_is_reversible_and_is_not_deletion() -> None:
    """`BLOCKED` es la limitación del tratamiento del art. 18 GDPR."""
    session = (
        _session()
        .transition_to(SessionState.COLLECTING)
        .transition_to(SessionState.PROCESSING)
        .transition_to(SessionState.DECIDED)
        .seal()
    )
    blocked = session.block()
    assert blocked.state is SessionState.BLOCKED
    assert blocked.transition_to(SessionState.RETAINED).state is SessionState.RETAINED
    assert blocked.artifacts == session.artifacts


# --------------------------------------------------------------------------
# Invariantes
# --------------------------------------------------------------------------


def test_i2_step_cannot_run_before_dependency() -> None:
    session = _session()
    assert session.can_run("align") is True
    assert session.can_run("ocr") is False
    with pytest.raises(DomainError):
        session.start_step("ocr", ProviderRef("p"))


def test_i2_negative_dependency_satisfies() -> None:
    """`NEGATIVE` es terminal exitoso desde el punto de vista del pipeline."""
    session = _session()
    session = session.start_step("align", ProviderRef("p"))
    session = session.complete_step("align", state=StepState.NEGATIVE)
    assert session.can_run("ocr") is True


def test_i2_failed_dependency_blocks() -> None:
    session = _session()
    session = session.start_step("align", ProviderRef("p"))
    session = session.complete_step("align", state=StepState.FAILED, error_code="OG_PROVIDER")
    assert session.can_run("ocr") is False


def test_i4_terminal_session_rejects_new_artifacts() -> None:
    session = (
        _session()
        .transition_to(SessionState.COLLECTING)
        .transition_to(SessionState.PROCESSING)
        .transition_to(SessionState.DECIDED)
    )
    artifact = Artifact(slot=ArtifactSlot.DOC_FRONT, ref=_ref(), data_class=DataClass.DOCUMENT)
    with pytest.raises(DomainError):
        session.register_artifact(artifact)


def test_i7_biometric_artifact_requires_purge_date() -> None:
    with pytest.raises(ValidationError) as excinfo:
        Artifact(slot=ArtifactSlot.SELFIE, ref=_ref(), data_class=DataClass.BIOMETRIC)
    assert "I7" in excinfo.value.message

    built = build_selfie_artifact(_ref(), purgeable_after_seconds=3600)
    assert built.purgeable_from is not None
    assert built.data_class is DataClass.BIOMETRIC


def test_register_artifact_replaces_same_slot_and_moves_to_collecting() -> None:
    session = _session()
    first = Artifact(slot=ArtifactSlot.DOC_FRONT, ref=_ref("tenants/acme/a"), data_class=DataClass.DOCUMENT)
    second = Artifact(slot=ArtifactSlot.DOC_FRONT, ref=_ref("tenants/acme/b"), data_class=DataClass.DOCUMENT)
    session = session.register_artifact(first).register_artifact(second)
    assert len(session.artifacts) == 1
    assert session.artifact(ArtifactSlot.DOC_FRONT) == second
    assert session.state is SessionState.COLLECTING


def test_complete_step_rejects_non_terminal_state() -> None:
    session = _session().start_step("align", ProviderRef("p"))
    with pytest.raises(DomainError):
        session.complete_step("align", state=StepState.RUNNING)


def test_evidence_is_appended_and_step_links_it() -> None:
    evidence = Evidence.create(
        step_id="align",
        kind=EvidenceKind.DOCUMENT_ALIGNMENT,
        provider=ProviderRef("p"),
        verdict=Verdict.PASS,
        scores={"sharpness": 0.9},
    )
    session = _session().start_step("align", ProviderRef("p"))
    session = session.complete_step("align", state=StepState.SUCCEEDED, evidence=evidence)
    assert session.evidences == (evidence,)
    assert session.step("align").evidence_id == evidence.evidence_id
    assert session.step("align").attempts == 1


def test_ready_steps_advances_with_the_graph() -> None:
    session = _session()
    assert [s.step_id for s in session.ready_steps()] == ["align"]
    session = session.start_step("align", ProviderRef("p")).complete_step(
        "align", state=StepState.SUCCEEDED
    )
    assert [s.step_id for s in session.ready_steps()] == ["ocr"]


def test_purge_clears_payload_but_keeps_identity() -> None:
    session = (
        _session()
        .transition_to(SessionState.COLLECTING)
        .transition_to(SessionState.PROCESSING)
        .transition_to(SessionState.DECIDED)
        .seal()
    )
    purged = session.purge()
    assert purged.state is SessionState.PURGED
    assert purged.artifacts == ()
    assert purged.evidences == ()
    assert purged.session_id == session.session_id
    assert purged.tenant_id == session.tenant_id


def test_is_expired() -> None:
    session = _session()
    assert session.is_expired(now=session.created_at) is False
    assert session.is_expired(now=session.created_at + timedelta(seconds=3601)) is True


def test_terminal_states_set_is_consistent_with_transitions() -> None:
    """Ningún estado terminal admite volver a `PROCESSING`."""
    for state in TERMINAL_STATES:
        assert SessionState.PROCESSING not in ALLOWED_TRANSITIONS[state]
