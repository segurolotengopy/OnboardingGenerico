"""Pruebas del motor de decisión: agregación, umbrales y auditabilidad."""

from __future__ import annotations

from typing import Mapping

import pytest

from onboarding_generico.domain.decision import (
    REASON_AML_HIT,
    REASON_DEFAULT_POLICY,
    REASON_DOC_EXPIRED,
    REASON_DOC_INCOHERENT,
    REASON_FACE_GREY_BAND,
    REASON_FACE_NO_MATCH,
    REASON_FORGERY_SUSPECTED,
    REASON_MISSING_EVIDENCE,
    REASON_MRZ_CHECK_DIGIT,
    REASON_OCR_LOW_CONFIDENCE,
    REASON_PAD_FAILED,
    REASON_PAD_INJECTION,
    DecisionEngine,
    DecisionThresholds,
)
from onboarding_generico.domain.enums import (
    DecisionIssuer,
    DecisionOutcome,
    EvidenceKind,
    RiskLevel,
    Verdict,
)
from onboarding_generico.domain.value_objects import Evidence, ProviderRef
from onboarding_generico.errors import ValidationError


def _evidence(
    kind: EvidenceKind,
    *,
    verdict: Verdict = Verdict.PASS,
    scores: Mapping[str, float] | None = None,
) -> Evidence:
    return Evidence.create(
        step_id=str(kind).lower(),
        kind=kind,
        provider=ProviderRef("p", "1.0"),
        verdict=verdict,
        scores=scores or {},
    )


def _engine(issuer: DecisionIssuer = DecisionIssuer.MIDDLEWARE, **overrides: float) -> DecisionEngine:
    return DecisionEngine(DecisionThresholds(**overrides), issuer=issuer)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Umbrales
# --------------------------------------------------------------------------


def test_thresholds_reject_inverted_grey_band() -> None:
    with pytest.raises(ValidationError):
        DecisionThresholds(face_match_min=0.70, face_match_grey_band_low=0.80)


def test_thresholds_reject_out_of_range() -> None:
    with pytest.raises(ValidationError):
        DecisionThresholds(liveness_min=1.5)


def test_thresholds_from_mapping_ignores_unknown_keys() -> None:
    thresholds = DecisionThresholds.from_mapping({"liveness_min": 0.95, "no_existe": 1})
    assert thresholds.liveness_min == 0.95


# --------------------------------------------------------------------------
# Reglas
# --------------------------------------------------------------------------


def test_clean_case_is_approved_with_default_reason() -> None:
    decision = _engine().evaluate(
        [
            _evidence(EvidenceKind.LIVENESS, scores={"liveness_score": 0.97}),
            _evidence(EvidenceKind.FACE_MATCH, scores={"similarity": 0.93}),
        ]
    )
    assert decision.outcome is DecisionOutcome.APPROVED
    assert decision.reason_codes == (REASON_DEFAULT_POLICY,)
    assert decision.risk_level is RiskLevel.LOW


def test_face_match_below_grey_band_is_rejected() -> None:
    decision = _engine().evaluate([_evidence(EvidenceKind.FACE_MATCH, scores={"similarity": 0.40})])
    assert decision.outcome is DecisionOutcome.REJECTED
    assert REASON_FACE_NO_MATCH in decision.reason_codes
    assert decision.risk_level is RiskLevel.HIGH


def test_face_match_inside_grey_band_goes_to_review() -> None:
    """La banda gris no fuerza un binario: deriva a persona."""
    decision = _engine().evaluate([_evidence(EvidenceKind.FACE_MATCH, scores={"similarity": 0.78})])
    assert decision.outcome is DecisionOutcome.MANUAL_REVIEW
    assert REASON_FACE_GREY_BAND in decision.reason_codes
    assert decision.risk_level is RiskLevel.MEDIUM


def test_liveness_below_threshold_is_rejected() -> None:
    decision = _engine().evaluate([_evidence(EvidenceKind.LIVENESS, scores={"liveness_score": 0.5})])
    assert decision.outcome is DecisionOutcome.REJECTED
    assert REASON_PAD_FAILED in decision.reason_codes


def test_injection_detected_is_rejected_regardless_of_score() -> None:
    """El PAD no se degrada: una inyección detectada es terminal."""
    decision = _engine().evaluate(
        [
            _evidence(
                EvidenceKind.LIVENESS,
                scores={"liveness_score": 0.99, "injection_detected": 1.0},
            )
        ]
    )
    assert decision.outcome is DecisionOutcome.REJECTED
    assert REASON_PAD_INJECTION in decision.reason_codes
    assert REASON_PAD_FAILED not in decision.reason_codes
    assert decision.risk_level is RiskLevel.HIGH


def test_mrz_check_digit_failure_goes_to_review() -> None:
    decision = _engine().evaluate(
        [_evidence(EvidenceKind.MRZ, verdict=Verdict.FAIL, scores={"checks_failed": 2.0})]
    )
    assert decision.outcome is DecisionOutcome.MANUAL_REVIEW
    assert REASON_MRZ_CHECK_DIGIT in decision.reason_codes


def test_cross_field_discrepancies_go_to_review() -> None:
    decision = _engine().evaluate(
        [_evidence(EvidenceKind.CROSS_FIELD, scores={"discrepancies": 1.0})]
    )
    assert REASON_DOC_INCOHERENT in decision.reason_codes


def test_too_many_minor_discrepancies_go_to_review() -> None:
    decision = _engine().evaluate(
        [_evidence(EvidenceKind.CROSS_FIELD, scores={"minor_discrepancies": 5.0})]
    )
    assert REASON_DOC_INCOHERENT in decision.reason_codes


def test_expired_document_is_rejected() -> None:
    decision = _engine().evaluate([_evidence(EvidenceKind.CROSS_FIELD, scores={"expired": 1.0})])
    assert decision.outcome is DecisionOutcome.REJECTED
    assert REASON_DOC_EXPIRED in decision.reason_codes


def test_low_ocr_confidence_goes_to_review() -> None:
    decision = _engine().evaluate(
        [_evidence(EvidenceKind.OCR, scores={"min_field_confidence": 0.40})]
    )
    assert REASON_OCR_LOW_CONFIDENCE in decision.reason_codes


def test_forgery_above_threshold_is_high_risk() -> None:
    decision = _engine().evaluate(
        [_evidence(EvidenceKind.FORGERY, scores={"forgery_score": 0.85})]
    )
    assert REASON_FORGERY_SUSPECTED in decision.reason_codes
    assert decision.risk_level is RiskLevel.HIGH


def test_aml_hit_goes_to_review_not_rejection() -> None:
    """El sujeto obligado decide sobre una coincidencia AML, no el middleware."""
    decision = _engine().evaluate([_evidence(EvidenceKind.AML, scores={"strong_hits": 2.0})])
    assert decision.outcome is DecisionOutcome.MANUAL_REVIEW
    assert REASON_AML_HIT in decision.reason_codes


def test_inconclusive_evidence_goes_to_review() -> None:
    decision = _engine().evaluate([_evidence(EvidenceKind.OCR, verdict=Verdict.INCONCLUSIVE)])
    assert decision.outcome is DecisionOutcome.MANUAL_REVIEW


def test_missing_required_evidence_goes_to_review() -> None:
    engine = DecisionEngine(
        issuer=DecisionIssuer.MIDDLEWARE, required_kinds=[EvidenceKind.LIVENESS]
    )
    decision = engine.evaluate([])
    assert decision.outcome is DecisionOutcome.MANUAL_REVIEW
    assert REASON_MISSING_EVIDENCE in decision.reason_codes


# --------------------------------------------------------------------------
# Agregación y determinismo
# --------------------------------------------------------------------------


def test_most_severe_outcome_wins() -> None:
    decision = _engine().evaluate(
        [
            _evidence(EvidenceKind.AML, scores={"strong_hits": 1.0}),  # revisión
            _evidence(EvidenceKind.FACE_MATCH, scores={"similarity": 0.10}),  # rechazo
        ]
    )
    assert decision.outcome is DecisionOutcome.REJECTED
    assert REASON_AML_HIT in decision.reason_codes
    assert REASON_FACE_NO_MATCH in decision.reason_codes


def test_evaluation_is_deterministic() -> None:
    evidences = [
        _evidence(EvidenceKind.FACE_MATCH, scores={"similarity": 0.78}),
        _evidence(EvidenceKind.LIVENESS, scores={"liveness_score": 0.95}),
    ]
    engine = _engine()
    first = engine.evaluate(evidences)
    second = engine.evaluate(evidences)
    assert first.outcome is second.outcome
    assert first.reason_codes == second.reason_codes
    assert first.risk_level is second.risk_level


def test_reasons_carry_threshold_and_observed_value() -> None:
    """Sin umbral y valor observado la decisión no es reproducible."""
    decision = _engine().evaluate([_evidence(EvidenceKind.FACE_MATCH, scores={"similarity": 0.78})])
    reason = next(r for r in decision.reasons if r.code == REASON_FACE_GREY_BAND)
    assert reason.observed == pytest.approx(0.78)
    assert reason.threshold == pytest.approx(0.82)
    assert reason.kind is EvidenceKind.FACE_MATCH


def test_tenant_thresholds_change_the_outcome() -> None:
    """El mismo hecho con otro umbral produce otro veredicto, y queda registrado."""
    evidence = [_evidence(EvidenceKind.FACE_MATCH, scores={"similarity": 0.78})]
    strict = _engine(face_match_min=0.90, face_match_grey_band_low=0.85).evaluate(evidence)
    lax = _engine(face_match_min=0.70, face_match_grey_band_low=0.60).evaluate(evidence)
    assert strict.outcome is DecisionOutcome.REJECTED
    assert lax.outcome is DecisionOutcome.APPROVED


# --------------------------------------------------------------------------
# Emisor del veredicto
# --------------------------------------------------------------------------


def test_signals_only_never_emits_a_verdict() -> None:
    """Obligatorio en Bolivia: art. 32(II) del Instructivo UIF."""
    decision = DecisionEngine(issuer=DecisionIssuer.SIGNALS_ONLY).evaluate(
        [_evidence(EvidenceKind.FACE_MATCH, scores={"similarity": 0.05})]
    )
    assert decision.outcome is DecisionOutcome.SIGNALS_ONLY
    assert decision.issuer is DecisionIssuer.SIGNALS_ONLY
    # Las señales siguen ahí: el requirente decide con ellas.
    assert REASON_FACE_NO_MATCH in decision.reason_codes
    assert decision.risk_level is RiskLevel.HIGH


def test_decision_serialization_has_no_pii() -> None:
    decision = _engine().evaluate([_evidence(EvidenceKind.FACE_MATCH, scores={"similarity": 0.5})])
    serialized = str(decision.as_dict())
    assert "similarity" not in serialized or "0.5" in serialized
    assert "first_name" not in serialized
    assert decision.as_dict()["issuer"] == "MIDDLEWARE"
