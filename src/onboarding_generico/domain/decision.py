"""Motor de decisión: agrega evidencias contra umbrales del tenant.

Propiedades exigidas:

- **Determinista**: mismas evidencias y mismos umbrales, mismo veredicto.
- **Auditable**: cada veredicto viene acompañado de la lista ordenada de
  razones, con el umbral aplicado y el valor observado. Una decisión sin
  razón trazable no es defendible ante un regulador.
- **Total**: existe siempre una salida, incluso si no se dispara ninguna
  regla; en ese caso rige `default_outcome`.
- **Consciente de la jurisdicción**: con `DecisionIssuer.SIGNALS_ONLY` el
  middleware **no emite veredicto**, solo señales. Es obligatorio en Bolivia
  (art. 32(II) del Instructivo UIF: la Debida Diligencia no se delega).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..errors import ValidationError
from .enums import (
    DecisionIssuer,
    DecisionOutcome,
    DecisionSource,
    EvidenceKind,
    RiskLevel,
    Verdict,
)
from .value_objects import Evidence, utc_now

#: Códigos de razón estables. Forman parte del contrato con el requirente.
REASON_MRZ_CHECK_DIGIT = "MRZ_CHECK_DIGIT_FAILED"
REASON_DOC_INCOHERENT = "DOC_INCOHERENT"
REASON_DOC_EXPIRED = "DOC_EXPIRED"
REASON_PAD_FAILED = "PAD_FAILED"
REASON_PAD_INJECTION = "PAD_INJECTION_DETECTED"
REASON_FACE_NO_MATCH = "FACE_NO_MATCH"
REASON_FACE_GREY_BAND = "FACE_GREY_BAND"
REASON_FORGERY_SUSPECTED = "FORGERY_SUSPECTED"
REASON_OCR_LOW_CONFIDENCE = "OCR_LOW_CONFIDENCE"
REASON_AML_HIT = "AML_HIT"
REASON_REGISTRY_MISMATCH = "REGISTRY_MISMATCH"
REASON_MISSING_EVIDENCE = "MISSING_REQUIRED_EVIDENCE"
REASON_INCONCLUSIVE_STEP = "INCONCLUSIVE_STEP"
REASON_DEFAULT_POLICY = "DEFAULT_POLICY"


@dataclass(frozen=True, slots=True)
class DecisionThresholds:
    """Umbrales configurables por tenant.

    Los valores por defecto siguen SP 800-63A-4 para la operación 1:1
    (FMR objetivo 1:10.000, FNMR objetivo 1:100) y la práctica de banda gris
    documentada en el doc 09.
    """

    face_match_min: float = 0.82
    face_match_grey_band_low: float = 0.74
    liveness_min: float = 0.90
    ocr_min_field_confidence: float = 0.85
    forgery_max_score: float = 0.30
    max_cross_field_discrepancies: int = 0
    max_minor_discrepancies: int = 2
    aml_review_on_hits: int = 1
    require_mrz: bool = False
    require_registry_match: bool = False

    def __post_init__(self) -> None:
        if self.face_match_grey_band_low > self.face_match_min:
            raise ValidationError(
                "el piso de la banda gris no puede superar el umbral de coincidencia",
                field="face_match_grey_band_low",
            )
        for name in (
            "face_match_min",
            "face_match_grey_band_low",
            "liveness_min",
            "ocr_min_field_confidence",
            "forgery_max_score",
        ):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValidationError(f"{name} debe estar en [0, 1]", field=name)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> DecisionThresholds:
        """Construye desde la configuración del tenant, ignorando claves ajenas."""
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass(frozen=True, slots=True)
class DecisionReason:
    """Razón auditable de una decisión.

    Lleva el umbral aplicado y el valor observado para que la decisión sea
    reproducible sin acceder a los datos originales. **No lleva PII**: el
    campo `field_name` es un nombre de campo, nunca su valor.
    """

    code: str
    kind: EvidenceKind | None = None
    observed: float | None = None
    threshold: float | None = None
    field_name: str | None = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "kind": str(self.kind) if self.kind else None,
            "observed": self.observed,
            "threshold": self.threshold,
            "field_name": self.field_name,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class Decision:
    """Veredicto sellado de la sesión (objeto de valor inmutable, I5)."""

    outcome: DecisionOutcome
    issuer: DecisionIssuer
    source: DecisionSource
    reasons: tuple[DecisionReason, ...] = ()
    risk_level: RiskLevel = RiskLevel.LOW
    decided_at: datetime = field(default_factory=utc_now)
    decided_by: str = "system"
    evidence_manifest: str = ""

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(r.code for r in self.reasons)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": str(self.outcome),
            "issuer": str(self.issuer),
            "source": str(self.source),
            "risk_level": str(self.risk_level),
            "reasons": [r.as_dict() for r in self.reasons],
            "decided_at": self.decided_at.isoformat(),
            "decided_by": self.decided_by,
            "evidence_manifest": self.evidence_manifest,
        }


#: Severidad relativa de cada veredicto; gana el más severo.
_OUTCOME_SEVERITY: dict[DecisionOutcome, int] = {
    DecisionOutcome.APPROVED: 0,
    DecisionOutcome.INCONCLUSIVE: 1,
    DecisionOutcome.MANUAL_REVIEW: 2,
    DecisionOutcome.REJECTED: 3,
}


class DecisionEngine:
    """Agrega evidencias y emite un veredicto con razones auditables."""

    __slots__ = ("issuer", "required_kinds", "thresholds")

    def __init__(
        self,
        thresholds: DecisionThresholds | None = None,
        *,
        issuer: DecisionIssuer = DecisionIssuer.SIGNALS_ONLY,
        required_kinds: Iterable[EvidenceKind] = (),
    ) -> None:
        self.thresholds = thresholds or DecisionThresholds()
        self.issuer = issuer
        self.required_kinds = tuple(required_kinds)

    # -- API pública -------------------------------------------------------

    def evaluate(
        self,
        evidences: Sequence[Evidence],
        *,
        decided_by: str = "system",
        source: DecisionSource = DecisionSource.AUTOMATED_POLICY,
        evidence_manifest: str = "",
    ) -> Decision:
        """Evalúa el conjunto de evidencias y devuelve la decisión sellada."""
        reasons: list[DecisionReason] = []
        outcome = DecisionOutcome.APPROVED

        outcome = self._worse(outcome, self._check_required(evidences, reasons))
        by_kind = _index_by_kind(evidences)

        for rule in (
            self._rule_mrz,
            self._rule_cross_field,
            self._rule_ocr_confidence,
            self._rule_forgery,
            self._rule_liveness,
            self._rule_face_match,
            self._rule_aml,
            self._rule_registry,
            self._rule_inconclusive,
        ):
            outcome = self._worse(outcome, rule(by_kind, reasons))

        if not reasons:
            reasons.append(
                DecisionReason(code=REASON_DEFAULT_POLICY, detail="ninguna regla se disparó")
            )

        final_outcome = outcome
        if self.issuer is DecisionIssuer.SIGNALS_ONLY:
            # El middleware no emite veredicto: solo señales y evidencias.
            final_outcome = DecisionOutcome.SIGNALS_ONLY

        return Decision(
            outcome=final_outcome,
            issuer=self.issuer,
            source=source,
            reasons=tuple(reasons),
            risk_level=self._risk_level(outcome, reasons),
            decided_by=decided_by,
            evidence_manifest=evidence_manifest,
        )

    # -- Reglas ------------------------------------------------------------

    def _check_required(
        self, evidences: Sequence[Evidence], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        present = {e.kind for e in evidences}
        missing = [kind for kind in self.required_kinds if kind not in present]
        if not missing:
            return DecisionOutcome.APPROVED
        for kind in missing:
            reasons.append(
                DecisionReason(
                    code=REASON_MISSING_EVIDENCE,
                    kind=kind,
                    detail="la política exige esta evidencia y no está presente",
                )
            )
        return DecisionOutcome.MANUAL_REVIEW

    def _rule_mrz(
        self, by_kind: Mapping[EvidenceKind, tuple[Evidence, ...]], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        items = by_kind.get(EvidenceKind.MRZ, ())
        if not items:
            if self.thresholds.require_mrz:
                reasons.append(
                    DecisionReason(
                        code=REASON_MISSING_EVIDENCE,
                        kind=EvidenceKind.MRZ,
                        detail="el tenant exige MRZ legible",
                    )
                )
                return DecisionOutcome.MANUAL_REVIEW
            return DecisionOutcome.APPROVED
        worst = DecisionOutcome.APPROVED
        for evidence in items:
            if evidence.verdict is Verdict.FAIL:
                reasons.append(
                    DecisionReason(
                        code=REASON_MRZ_CHECK_DIGIT,
                        kind=EvidenceKind.MRZ,
                        observed=evidence.score("checks_failed"),
                        threshold=0.0,
                        detail="uno o más dígitos de control 7-3-1 no cuadran",
                    )
                )
                worst = self._worse(worst, DecisionOutcome.MANUAL_REVIEW)
        return worst

    def _rule_cross_field(
        self, by_kind: Mapping[EvidenceKind, tuple[Evidence, ...]], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        worst = DecisionOutcome.APPROVED
        for evidence in by_kind.get(EvidenceKind.CROSS_FIELD, ()):
            major = evidence.score("discrepancies")
            minor = evidence.score("minor_discrepancies")
            if major > self.thresholds.max_cross_field_discrepancies:
                reasons.append(
                    DecisionReason(
                        code=REASON_DOC_INCOHERENT,
                        kind=EvidenceKind.CROSS_FIELD,
                        observed=major,
                        threshold=float(self.thresholds.max_cross_field_discrepancies),
                        detail="discrepancias entre MRZ y datos extraídos",
                    )
                )
                worst = self._worse(worst, DecisionOutcome.MANUAL_REVIEW)
            elif minor > self.thresholds.max_minor_discrepancies:
                reasons.append(
                    DecisionReason(
                        code=REASON_DOC_INCOHERENT,
                        kind=EvidenceKind.CROSS_FIELD,
                        observed=minor,
                        threshold=float(self.thresholds.max_minor_discrepancies),
                        detail="demasiadas diferencias de un carácter, posible OCR degradado",
                    )
                )
                worst = self._worse(worst, DecisionOutcome.MANUAL_REVIEW)
            if evidence.score("expired", 0.0) >= 1.0:
                reasons.append(
                    DecisionReason(
                        code=REASON_DOC_EXPIRED,
                        kind=EvidenceKind.CROSS_FIELD,
                        detail="el documento está caducado",
                    )
                )
                worst = self._worse(worst, DecisionOutcome.REJECTED)
        return worst

    def _rule_ocr_confidence(
        self, by_kind: Mapping[EvidenceKind, tuple[Evidence, ...]], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        worst = DecisionOutcome.APPROVED
        for kind in (EvidenceKind.OCR, EvidenceKind.SEMANTIC_EXTRACTION):
            for evidence in by_kind.get(kind, ()):
                confidence = evidence.score("min_field_confidence", 1.0)
                if confidence < self.thresholds.ocr_min_field_confidence:
                    reasons.append(
                        DecisionReason(
                            code=REASON_OCR_LOW_CONFIDENCE,
                            kind=kind,
                            observed=confidence,
                            threshold=self.thresholds.ocr_min_field_confidence,
                            field_name=str(evidence.scores.get("worst_field", "")) or None,
                        )
                    )
                    worst = self._worse(worst, DecisionOutcome.MANUAL_REVIEW)
        return worst

    def _rule_forgery(
        self, by_kind: Mapping[EvidenceKind, tuple[Evidence, ...]], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        worst = DecisionOutcome.APPROVED
        for evidence in by_kind.get(EvidenceKind.FORGERY, ()):
            score = evidence.score("forgery_score")
            if score > self.thresholds.forgery_max_score:
                reasons.append(
                    DecisionReason(
                        code=REASON_FORGERY_SUSPECTED,
                        kind=EvidenceKind.FORGERY,
                        observed=score,
                        threshold=self.thresholds.forgery_max_score,
                    )
                )
                worst = self._worse(worst, DecisionOutcome.MANUAL_REVIEW)
        return worst

    def _rule_liveness(
        self, by_kind: Mapping[EvidenceKind, tuple[Evidence, ...]], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        worst = DecisionOutcome.APPROVED
        for evidence in by_kind.get(EvidenceKind.LIVENESS, ()):
            if evidence.score("injection_detected") >= 1.0:
                reasons.append(
                    DecisionReason(
                        code=REASON_PAD_INJECTION,
                        kind=EvidenceKind.LIVENESS,
                        detail="inyección detectada; el PAD no se degrada ni se reintenta",
                    )
                )
                worst = self._worse(worst, DecisionOutcome.REJECTED)
                continue
            score = evidence.score("liveness_score")
            if score < self.thresholds.liveness_min:
                reasons.append(
                    DecisionReason(
                        code=REASON_PAD_FAILED,
                        kind=EvidenceKind.LIVENESS,
                        observed=score,
                        threshold=self.thresholds.liveness_min,
                    )
                )
                worst = self._worse(worst, DecisionOutcome.REJECTED)
        return worst

    def _rule_face_match(
        self, by_kind: Mapping[EvidenceKind, tuple[Evidence, ...]], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        worst = DecisionOutcome.APPROVED
        for evidence in by_kind.get(EvidenceKind.FACE_MATCH, ()):
            similarity = evidence.score("similarity")
            if similarity >= self.thresholds.face_match_min:
                continue
            if similarity >= self.thresholds.face_match_grey_band_low:
                reasons.append(
                    DecisionReason(
                        code=REASON_FACE_GREY_BAND,
                        kind=EvidenceKind.FACE_MATCH,
                        observed=similarity,
                        threshold=self.thresholds.face_match_min,
                        detail="similitud en banda gris; se deriva a revisión humana",
                    )
                )
                worst = self._worse(worst, DecisionOutcome.MANUAL_REVIEW)
            else:
                reasons.append(
                    DecisionReason(
                        code=REASON_FACE_NO_MATCH,
                        kind=EvidenceKind.FACE_MATCH,
                        observed=similarity,
                        threshold=self.thresholds.face_match_grey_band_low,
                    )
                )
                worst = self._worse(worst, DecisionOutcome.REJECTED)
        return worst

    def _rule_aml(
        self, by_kind: Mapping[EvidenceKind, tuple[Evidence, ...]], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        worst = DecisionOutcome.APPROVED
        for evidence in by_kind.get(EvidenceKind.AML, ()):
            hits = evidence.score("strong_hits")
            if hits >= self.thresholds.aml_review_on_hits:
                reasons.append(
                    DecisionReason(
                        code=REASON_AML_HIT,
                        kind=EvidenceKind.AML,
                        observed=hits,
                        threshold=float(self.thresholds.aml_review_on_hits),
                        detail="coincidencias fuertes en listas; decide el sujeto obligado",
                    )
                )
                worst = self._worse(worst, DecisionOutcome.MANUAL_REVIEW)
        return worst

    def _rule_registry(
        self, by_kind: Mapping[EvidenceKind, tuple[Evidence, ...]], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        items = by_kind.get(EvidenceKind.REGISTRY, ())
        if not items and self.thresholds.require_registry_match:
            reasons.append(
                DecisionReason(
                    code=REASON_MISSING_EVIDENCE,
                    kind=EvidenceKind.REGISTRY,
                    detail="el tenant exige verificación contra registro oficial",
                )
            )
            return DecisionOutcome.MANUAL_REVIEW
        worst = DecisionOutcome.APPROVED
        for evidence in items:
            if evidence.verdict is not Verdict.PASS:
                reasons.append(
                    DecisionReason(
                        code=REASON_REGISTRY_MISMATCH,
                        kind=EvidenceKind.REGISTRY,
                        detail="el registro oficial no confirma los datos",
                    )
                )
                worst = self._worse(worst, DecisionOutcome.MANUAL_REVIEW)
        return worst

    def _rule_inconclusive(
        self, by_kind: Mapping[EvidenceKind, tuple[Evidence, ...]], reasons: list[DecisionReason]
    ) -> DecisionOutcome:
        worst = DecisionOutcome.APPROVED
        for kind, items in by_kind.items():
            for evidence in items:
                if evidence.verdict is Verdict.INCONCLUSIVE:
                    reasons.append(
                        DecisionReason(
                            code=REASON_INCONCLUSIVE_STEP,
                            kind=kind,
                            detail="el proveedor no alcanzó confianza suficiente",
                        )
                    )
                    worst = self._worse(worst, DecisionOutcome.MANUAL_REVIEW)
        return worst

    # -- Auxiliares --------------------------------------------------------

    @staticmethod
    def _worse(left: DecisionOutcome, right: DecisionOutcome) -> DecisionOutcome:
        return left if _OUTCOME_SEVERITY[left] >= _OUTCOME_SEVERITY[right] else right

    @staticmethod
    def _risk_level(outcome: DecisionOutcome, reasons: Sequence[DecisionReason]) -> RiskLevel:
        codes = {r.code for r in reasons}
        if REASON_PAD_INJECTION in codes or REASON_FORGERY_SUSPECTED in codes:
            return RiskLevel.HIGH
        if outcome is DecisionOutcome.REJECTED:
            return RiskLevel.HIGH
        if outcome is DecisionOutcome.MANUAL_REVIEW:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW


def _index_by_kind(evidences: Sequence[Evidence]) -> dict[EvidenceKind, tuple[Evidence, ...]]:
    index: dict[EvidenceKind, list[Evidence]] = {}
    for evidence in evidences:
        index.setdefault(evidence.kind, []).append(evidence)
    return {kind: tuple(items) for kind, items in index.items()}


__all__ = [
    "REASON_AML_HIT",
    "REASON_DEFAULT_POLICY",
    "REASON_DOC_EXPIRED",
    "REASON_DOC_INCOHERENT",
    "REASON_FACE_GREY_BAND",
    "REASON_FACE_NO_MATCH",
    "REASON_FORGERY_SUSPECTED",
    "REASON_INCONCLUSIVE_STEP",
    "REASON_MISSING_EVIDENCE",
    "REASON_MRZ_CHECK_DIGIT",
    "REASON_OCR_LOW_CONFIDENCE",
    "REASON_PAD_FAILED",
    "REASON_PAD_INJECTION",
    "REASON_REGISTRY_MISMATCH",
    "Decision",
    "DecisionEngine",
    "DecisionReason",
    "DecisionThresholds",
]
