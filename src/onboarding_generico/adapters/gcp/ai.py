"""Adaptadores de GCP para OCR y LLM.

- **Document AI**: se usa el procesador **Enterprise Document OCR** genérico,
  no los procesadores de identidad. Estos últimos cubren solo EE. UU.
  (licencias de los 50 estados y D. C., pasaportes, proofing) y además tienen
  deprecaciones activas con apagado el **30 de junio de 2026**, incluida la
  licencia de conducir francesa. Hay paridad en la limitación con
  `AnalyzeID`: fuera de EE. UU. no sirve ninguno de los dos.
- **Claude en Vertex AI / Model Garden**: es el componente que **elimina** la
  brecha de cobertura documental, porque tiene paridad total con Bedrock. El
  diferenciador del producto queda portable.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from ...config import Settings
from ...domain.value_objects import Confidence, ObjectRef, TenantId
from ...errors import ProviderContractViolationError, ProviderUnavailableError
from ...ports.llm import ExtractionResult, LlmPort, LlmUsage
from ...ports.ocr import BoundingBox, OcrPort, OcrResult, TextBlock
from ._client import documentai_client, require


class DocumentAiOcr(OcrPort):
    """OCR genérico con el procesador Enterprise Document OCR."""

    __slots__ = ("_settings", "_processor_id", "_location")

    PROVIDER_ID = "documentai_ocr"

    def __init__(self, settings: Settings, processor_id: str = "", location: str = "us") -> None:
        self._settings = settings
        self._processor_id = processor_id
        self._location = location

    def detect_text(
        self,
        tenant_id: TenantId,
        ref: ObjectRef,
        *,
        page: str = "FRONT",
        languages: Sequence[str] = (),
    ) -> OcrResult:
        if not self._processor_id:
            raise ProviderUnavailableError(
                "no hay procesador de Document AI configurado", provider_id=self.PROVIDER_ID
            )
        client = documentai_client(self._location)
        name = (
            f"projects/{self._settings.gcp_project}/locations/{self._location}"
            f"/processors/{self._processor_id}"
        )
        try:
            response = client.process_document(
                request={
                    "name": name,
                    "gcs_document": {"gcs_uri": ref.uri, "mime_type": ref.content_type},
                }
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError(
                "Document AI no respondió", provider_id=self.PROVIDER_ID
            ) from exc

        document = response.document
        blocks: list[TextBlock] = []
        for document_page in document.pages:
            for line in document_page.lines:
                segments = line.layout.text_anchor.text_segments
                text = "".join(
                    document.text[int(s.start_index) : int(s.end_index)] for s in segments
                )
                vertices = list(line.layout.bounding_poly.normalized_vertices)
                box = None
                if vertices:
                    xs = [v.x for v in vertices]
                    ys = [v.y for v in vertices]
                    box = BoundingBox(
                        left=min(xs), top=min(ys), width=max(xs) - min(xs), height=max(ys) - min(ys)
                    )
                blocks.append(
                    TextBlock(
                        text=text.strip(),
                        confidence=Confidence(float(line.layout.confidence)),
                        box=box,
                        block_type="LINE",
                    )
                )
        return OcrResult(
            blocks=tuple(blocks),
            provider_id=self.PROVIDER_ID,
            page=page,
            language=languages[0] if languages else "und",
        )


class ClaudeOnVertexLlm(LlmPort):
    """Extracción estructurada con Claude en Vertex AI.

    Sobre el *context caching* de Vertex: como en Bedrock, la reducción
    anunciada es de **coste**, no de tokens, y tiene mínimos por checkpoint.
    En tenants de bajo volumen puede salir neto negativo, así que se activa
    por tenant y no globalmente.
    """

    __slots__ = ("_settings", "_model_id", "_location")

    PROVIDER_ID = "vertex_claude"

    def __init__(self, settings: Settings, model_id: str = "", location: str = "us-east5") -> None:
        self._settings = settings
        self._model_id = model_id or "claude-sonnet-4-5@20250929"
        self._location = location

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
        module = require("anthropic", "anthropic[vertex]")
        client = module.AnthropicVertex(region=self._location, project_id=self._settings.gcp_project)

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for ref in image_refs:
            raise NotImplementedError(
                "Vertex no acepta punteros gs:// en el contenido del mensaje de Claude: la imagen "
                "hay que enviarla en base64. Falta decidir dónde se hace esa descarga y "
                f"codificación de {ref.uri}: en el worker (memoria proporcional al tamaño de la "
                "imagen, con el tope de 32 GiB por instancia de Cloud Run) o en un servicio de "
                "preparación aparte que además redimensione. Es una decisión de coste y de "
                "superficie de exposición del dato biométrico."
            )
        if enable_prompt_cache:
            content[0]["cache_control"] = {"type": "ephemeral"}

        try:
            response = client.messages.create(
                model=self._model_id,
                max_tokens=2048,
                messages=[{"role": "user", "content": content}],
                tools=[
                    {
                        "name": "emit_identity_claims",
                        "description": "Emite los campos de identidad extraídos del documento.",
                        "input_schema": dict(schema),
                    }
                ],
                tool_choice={"type": "tool", "name": "emit_identity_claims"},
            )
        except Exception as exc:  # noqa: BLE001
            raise ProviderUnavailableError(
                "Vertex AI no respondió", provider_id=self.PROVIDER_ID
            ) from exc

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None:
            raise ProviderContractViolationError(
                "el modelo no emitió la herramienta esperada", provider_id=self.PROVIDER_ID
            )
        data = dict(tool_use.input)
        return ExtractionResult(
            data=data,
            confidence=Confidence(1.0 if data else 0.0),
            field_confidence={},
            usage=LlmUsage(
                input_tokens=int(response.usage.input_tokens),
                output_tokens=int(response.usage.output_tokens),
                cached_input_tokens=int(getattr(response.usage, "cache_read_input_tokens", 0) or 0),
            ),
            provider_id=self.PROVIDER_ID,
            model_id=self._model_id,
        )


__all__ = ["ClaudeOnVertexLlm", "DocumentAiOcr"]
