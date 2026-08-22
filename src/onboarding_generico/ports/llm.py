"""Puerto de LLM multimodal para extracción estructurada.

Este es el componente que **elimina la brecha 8** de paridad: como los
procesadores de identidad de ambas nubes cubren esencialmente EE. UU., el
patrón portable es OCR genérico + LLM multimodal por país, y Claude tiene
paridad total (Bedrock en AWS, Model Garden / Vertex en GCP).

Sobre el *prompt caching*: la reducción de "hasta 90 %" es de **coste**, no de
tokens (los tokens se siguen contando y se facturan con descuento), y el
"hasta 85 %" de latencia es un techo de marketing. Hay mínimos por checkpoint
(1.024–4.096 tokens), máximo 4 checkpoints por petición y TTL de 5 minutos
(1 hora opcional en algunos modelos). En tenants de bajo volumen el balance
puede ser **neto negativo**, así que la caché es opcional por tenant.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..domain.value_objects import Confidence, ObjectRef, TenantId


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """Consumo de la llamada, para atribución de coste por tenant."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Salida estructurada del LLM.

    `data` **contiene PII** y nunca se registra; `usage` y `confidence` sí son
    seguros para métricas.
    """

    data: Mapping[str, Any]
    confidence: Confidence
    field_confidence: Mapping[str, float] = field(default_factory=dict)
    usage: LlmUsage = field(default_factory=LlmUsage)
    provider_id: str = "unknown"
    model_id: str = "unknown"

    @property
    def min_field_confidence(self) -> float:
        if not self.field_confidence:
            return float(self.confidence)
        return min(self.field_confidence.values())

    @property
    def worst_field(self) -> str:
        if not self.field_confidence:
            return ""
        return min(self.field_confidence.items(), key=lambda item: item[1])[0]

    def audit_summary(self) -> dict[str, object]:
        return {
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "confidence": float(self.confidence),
            "min_field_confidence": self.min_field_confidence,
            "worst_field": self.worst_field,
            "field_names": sorted(self.data.keys()),
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "cached_input_tokens": self.usage.cached_input_tokens,
        }


class LlmPort(abc.ABC):
    """Extracción estructurada guiada por esquema."""

    @abc.abstractmethod
    def extract_structured(
        self,
        tenant_id: TenantId,
        prompt: str,
        schema: Mapping[str, Any],
        image_refs: Sequence[ObjectRef] = (),
        *,
        template: str = "",
        enable_prompt_cache: bool = False,
    ) -> ExtractionResult:
        """Extrae campos conforme al esquema a partir de texto e imágenes.

        El adaptador valida la respuesta contra `schema` y lanza
        `ProviderContractViolationError` si no encaja: un LLM que devuelve un
        campo de más o con otro tipo es un fallo de contrato, no un dato.
        """


__all__ = ["ExtractionResult", "LlmPort", "LlmUsage"]
