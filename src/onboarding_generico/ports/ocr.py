"""Puerto de OCR genérico.

`AnalyzeID` de Textract y los procesadores de identidad de Document AI cubren
esencialmente EE. UU. (licencias de los 50 estados, pasaportes, proofing) y no
sirven para LATAM; además Document AI tiene deprecaciones activas con apagado
el 30 de junio de 2026. **Hay paridad en la limitación**, así que el patrón
portable es OCR genérico (`DetectDocumentText` / Enterprise Document OCR) más
un LLM multimodal para la extracción estructurada por país (ver `llm.py`).

Por eso este puerto expone OCR **genérico**: bloques de texto con geometría y
confianza, sin ninguna semántica de documento de identidad.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Sequence

from ..domain.value_objects import Confidence, ObjectRef, TenantId


@dataclass(frozen=True, slots=True)
class BoundingBox:
    """Caja normalizada al intervalo [0, 1] respecto del tamaño de la imagen."""

    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class TextBlock:
    """Bloque de texto detectado. **Contiene PII**: no se registra en logs."""

    text: str
    confidence: Confidence
    box: BoundingBox | None = None
    block_type: str = "LINE"


@dataclass(frozen=True, slots=True)
class OcrResult:
    """Salida del OCR genérico."""

    blocks: tuple[TextBlock, ...] = ()
    provider_id: str = "unknown"
    page: str = "FRONT"
    language: str = "und"
    warnings: tuple[str, ...] = field(default=())

    @property
    def text(self) -> str:
        """Texto plano concatenado, en orden de lectura."""
        return "\n".join(block.text for block in self.blocks)

    @property
    def min_confidence(self) -> float:
        if not self.blocks:
            return 0.0
        return min(float(block.confidence) for block in self.blocks)

    def audit_summary(self) -> dict[str, object]:
        """Resumen sin PII para el expediente."""
        return {
            "provider_id": self.provider_id,
            "page": self.page,
            "block_count": len(self.blocks),
            "min_confidence": self.min_confidence,
            "warnings": list(self.warnings),
        }


class OcrPort(abc.ABC):
    """Extracción de texto de una imagen de documento."""

    @abc.abstractmethod
    def detect_text(
        self,
        tenant_id: TenantId,
        ref: ObjectRef,
        *,
        page: str = "FRONT",
        languages: Sequence[str] = (),
    ) -> OcrResult:
        """Devuelve los bloques de texto de la imagen referenciada.

        Recibe un `ObjectRef`, nunca los bytes: el adaptador decide si usa una
        URL prefirmada o descarga el objeto.
        """


__all__ = ["BoundingBox", "OcrPort", "OcrResult", "TextBlock"]
