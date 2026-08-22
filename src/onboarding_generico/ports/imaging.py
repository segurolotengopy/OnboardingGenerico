"""Puertos de tratamiento de imagen del documento.

Agrupa `DocumentAlignmentPort` (rectificación de perspectiva y recorte) y
`ForgeryDetectionPort` (detección de manipulación). Ambos consumen y producen
`ObjectRef`: los binarios no viajan por el estado del orquestador.

Nota de licencias: `fbieberly/document_warp` y
`joellijo32/Document-Scanner-using-OpenCV` son MIT y sirven como código de
referencia; `YegorCherov/document-scanner` **no tiene licencia** (todos los
derechos reservados) y no se usa. Los pesos de TruFor arrastran restricciones
de uso no comercial independientes de la licencia del código.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

from ..domain.value_objects import ObjectRef, TenantId


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    """Resultado de la rectificación del documento."""

    aligned: ObjectRef
    detected: bool
    sharpness: float = 0.0
    glare: float = 0.0
    resolution_px: int = 0
    skew_degrees: float = 0.0
    provider_id: str = "unknown"

    def meets(self, *, min_sharpness: float, max_glare: float, min_resolution_px: int) -> bool:
        """Comprueba los umbrales de calidad de captura del paso."""
        return (
            self.detected
            and self.sharpness >= min_sharpness
            and self.glare <= max_glare
            and self.resolution_px >= min_resolution_px
        )

    def audit_summary(self) -> dict[str, object]:
        return {
            "detected": self.detected,
            "sharpness": self.sharpness,
            "glare": self.glare,
            "resolution_px": self.resolution_px,
            "skew_degrees": self.skew_degrees,
            "provider_id": self.provider_id,
        }


@dataclass(frozen=True, slots=True)
class ForgeryResult:
    """Resultado del análisis de manipulación del documento."""

    forgery_score: float
    threshold: float
    suspicious: bool
    signals: tuple[str, ...] = ()
    provider_id: str = "unknown"

    def audit_summary(self) -> dict[str, object]:
        return {
            "forgery_score": self.forgery_score,
            "threshold": self.threshold,
            "suspicious": self.suspicious,
            "signals": list(self.signals),
            "provider_id": self.provider_id,
        }


class DocumentAlignmentPort(abc.ABC):
    """Rectificación de perspectiva, recorte y medida de calidad de captura."""

    @abc.abstractmethod
    def align(self, tenant_id: TenantId, ref: ObjectRef, *, page: str = "FRONT") -> AlignmentResult:
        """Detecta el documento, lo rectifica y devuelve la imagen alineada.

        Si no detecta documento, devuelve `detected=False` con la referencia
        original: es el paso el que decide si eso obliga a recaptura.
        """


class ForgeryDetectionPort(abc.ABC):
    """Detección de alteración digital o física del documento."""

    @abc.abstractmethod
    def analyze(
        self, tenant_id: TenantId, ref: ObjectRef, *, threshold: float = 0.30
    ) -> ForgeryResult:
        """Analiza el documento y devuelve una puntuación de sospecha en [0, 1]."""


__all__ = [
    "AlignmentResult",
    "DocumentAlignmentPort",
    "ForgeryDetectionPort",
    "ForgeryResult",
]
