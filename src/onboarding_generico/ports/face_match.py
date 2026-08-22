"""Puerto de comparación facial 1:1.

Se separa deliberadamente de `LivenessPort`: el *face match* es **portable**
(InsightFace/ONNX en Cloud Run con GPU, o el servicio gestionado de cada
nube), mientras que el liveness no lo es.

Umbrales de referencia (SP 800-63A-4, operación 1:1): FMR objetivo
≤ 1:10.000 y FNMR objetivo ≤ 1:100. El umbral de similitud se calibra por
población; la banda gris deriva a revisión humana en vez de forzar un binario.

Nota de licencias: los pesos `buffalo_l` de InsightFace arrastran
restricciones de uso no comercial **independientes** de la licencia del
código. Verificar antes de desplegar en producción.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

from ..domain.value_objects import ObjectRef, TenantId


@dataclass(frozen=True, slots=True)
class FaceMatchResult:
    """Resultado de la comparación 1:1."""

    similarity: float
    threshold: float
    matched: bool
    provider_id: str = "unknown"
    model_version: str = "unknown"
    quality_reference: float = 0.0
    quality_candidate: float = 0.0

    def audit_summary(self) -> dict[str, object]:
        """Resumen sin PII: puntuaciones y umbral, nunca embeddings ni imágenes."""
        return {
            "similarity": self.similarity,
            "threshold": self.threshold,
            "matched": self.matched,
            "provider_id": self.provider_id,
            "model_version": self.model_version,
            "quality_reference": self.quality_reference,
            "quality_candidate": self.quality_candidate,
        }


class FaceMatchPort(abc.ABC):
    """Comparación facial entre el retrato del documento y la captura en vivo."""

    @abc.abstractmethod
    def compare(
        self,
        tenant_id: TenantId,
        reference: ObjectRef,
        candidate: ObjectRef,
        *,
        threshold: float = 0.82,
    ) -> FaceMatchResult:
        """Compara dos rostros y devuelve la similitud normalizada a [0, 1]."""

    @abc.abstractmethod
    def assess_quality(self, tenant_id: TenantId, ref: ObjectRef) -> float:
        """Calidad de la imagen facial en [0, 1] (ISO/IEC 39794-5).

        Se evalúa **antes** de comparar: una captura de baja calidad produce
        una similitud baja que no distingue entre "no es la persona" y "la
        foto no sirve".
        """


__all__ = ["FaceMatchPort", "FaceMatchResult"]
