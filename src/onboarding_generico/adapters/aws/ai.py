"""Adaptadores de AWS para OCR, LLM y liveness.

Tres advertencias que este módulo respeta y que conviene no perder:

1. **`AnalyzeID` cubre esencialmente EE. UU.** (licencias de los 50 estados y
   D. C., pasaportes, proofing). No sirve para LATAM. Por eso el adaptador de
   OCR usa `DetectDocumentText` genérico y la semántica la aporta el LLM.
2. **Prompt caching**: el "hasta 90 %" es reducción de **coste**, no de
   tokens; los tokens se siguen contando y se facturan con descuento. El
   "hasta 85 %" de latencia es un techo de marketing. Hay mínimos por
   checkpoint (1.024–4.096 tokens), máximo 4 checkpoints por petición y TTL
   de 5 minutos (1 hora opcional en algunos modelos). En tenants de bajo
   volumen puede salir **neto negativo**.
3. **Memoria de Lambda**: el rango real es 128 MB – 10.240 MB. No existe
   requisito de memoria ligado a AVX-512; la documentación de Lambda solo
   cubre AVX2 y `arm64` usa NEON.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ...config import Settings
from ...domain.value_objects import Confidence, ObjectRef, TenantId
from ...errors import ProviderContractViolationError, ProviderUnavailableError
from ...ports.liveness import LivenessPort, LivenessResult, LivenessSession
from ...ports.llm import ExtractionResult, LlmPort, LlmUsage
from ...ports.ocr import BoundingBox, OcrPort, OcrResult, TextBlock
from ._client import client


class TextractOcr(OcrPort):
    """OCR genérico con `DetectDocumentText`.

    Se usa la operación genérica y **no** `AnalyzeID`: este último está
    limitado a documentos estadounidenses y devolvería campos vacíos para un
    INE, una CI boliviana o una CI paraguaya.
    """

    __slots__ = ("_settings",)

    PROVIDER_ID = "textract_ocr"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def detect_text(
        self,
        tenant_id: TenantId,
        ref: ObjectRef,
        *,
        page: str = "FRONT",
        languages: Sequence[str] = (),
    ) -> OcrResult:
        try:
            response = client("textract", self._settings.region).detect_document_text(
                Document={"S3Object": {"Bucket": ref.bucket, "Name": ref.key}}
            )
        except Exception as exc:
            raise ProviderUnavailableError(
                "Textract no respondió", provider_id=self.PROVIDER_ID
            ) from exc

        blocks: list[TextBlock] = []
        for raw in response.get("Blocks", []):
            if raw.get("BlockType") != "LINE":
                continue
            geometry = raw.get("Geometry", {}).get("BoundingBox", {})
            blocks.append(
                TextBlock(
                    text=str(raw.get("Text", "")),
                    confidence=Confidence(float(raw.get("Confidence", 0.0)) / 100.0),
                    box=BoundingBox(
                        left=float(geometry.get("Left", 0.0)),
                        top=float(geometry.get("Top", 0.0)),
                        width=float(geometry.get("Width", 0.0)),
                        height=float(geometry.get("Height", 0.0)),
                    ),
                    block_type="LINE",
                )
            )
        return OcrResult(
            blocks=tuple(blocks),
            provider_id=self.PROVIDER_ID,
            page=page,
            language=languages[0] if languages else "und",
        )


class BedrockLlm(LlmPort):
    """Extracción estructurada con Claude en Amazon Bedrock.

    Este es el componente que elimina la brecha de cobertura documental fuera
    de EE. UU.: tiene paridad total con Vertex AI en GCP, de modo que el
    diferenciador del producto es portable.
    """

    __slots__ = ("_model_id", "_settings")

    PROVIDER_ID = "bedrock_claude"

    def __init__(self, settings: Settings, model_id: str = "") -> None:
        self._settings = settings
        self._model_id = model_id or "anthropic.claude-sonnet-4-5-v1:0"

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
        import json

        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for ref in image_refs:
            # Se pasa la referencia, no los bytes: el binario no atraviesa el
            # estado del orquestador ni el payload de la Lambda.
            content.append(
                {
                    "type": "image",
                    "source": {"type": "s3", "s3Location": {"uri": ref.uri, "bucketOwner": ""}},
                }
            )
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": content}],
            "tools": [
                {
                    "name": "emit_identity_claims",
                    "description": "Emite los campos de identidad extraídos del documento.",
                    "input_schema": dict(schema),
                }
            ],
            "tool_choice": {"type": "tool", "name": "emit_identity_claims"},
        }
        if enable_prompt_cache:
            # Máximo 4 checkpoints por petición; el mínimo por checkpoint es de
            # 1.024–4.096 tokens según el modelo. Por debajo, no se cachea nada
            # y solo se paga el sobrecoste de escritura de caché.
            content[0]["cache_control"] = {"type": "ephemeral"}

        try:
            response = client("bedrock-runtime", self._settings.region).invoke_model(
                modelId=self._model_id, body=json.dumps(body)
            )
        except Exception as exc:
            raise ProviderUnavailableError(
                "Bedrock no respondió", provider_id=self.PROVIDER_ID
            ) from exc

        payload = json.loads(response["body"].read())
        tool_use = next(
            (block for block in payload.get("content", []) if block.get("type") == "tool_use"), None
        )
        if tool_use is None:
            raise ProviderContractViolationError(
                "el modelo no emitió la herramienta esperada", provider_id=self.PROVIDER_ID
            )
        usage = payload.get("usage", {})
        data = dict(tool_use.get("input", {}))
        return ExtractionResult(
            data=data,
            confidence=Confidence(1.0 if data else 0.0),
            field_confidence=self._field_confidence(data, schema),
            usage=LlmUsage(
                input_tokens=int(usage.get("input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                cached_input_tokens=int(usage.get("cache_read_input_tokens", 0)),
                cache_write_tokens=int(usage.get("cache_creation_input_tokens", 0)),
            ),
            provider_id=self.PROVIDER_ID,
            model_id=self._model_id,
        )

    def _field_confidence(
        self, data: Mapping[str, Any], schema: Mapping[str, Any]
    ) -> dict[str, float]:
        raise NotImplementedError(
            "Falta decidir cómo se deriva la confianza por campo de un LLM que no emite "
            "logprobs por campo. Las opciones son: (a) pedir al modelo una confianza "
            "autodeclarada, que es poco fiable; (b) cruzar contra el OCR y usar la confianza de "
            "Textract; (c) doble pasada con dos modelos y comparar. Cada una tiene un coste y una "
            "fiabilidad distintos, y la elección afecta directamente al umbral de derivación a "
            "revisión humana."
        )


class RekognitionLiveness(LivenessPort):
    """Face Liveness de Amazon Rekognition.

    **Este adaptador no tiene equivalente en GCP.** Además, su parte de
    cliente es un SDK de frontend: portarlo a GCP no es trabajo de
    infraestructura, es trabajo de app móvil o web. Por eso la recomendación
    de diseño es usar un SaaS certificado en ambas nubes.
    """

    __slots__ = ("_settings",)

    PROVIDER_ID = "rekognition_liveness"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def create_session(self, tenant_id: TenantId, *, ttl_seconds: int = 300) -> LivenessSession:
        response = client("rekognition", self._settings.region).create_face_liveness_session(
            Settings={
                "OutputConfig": {
                    "S3Bucket": self._settings.artifact_bucket,
                    "S3KeyPrefix": f"tenants/{tenant_id.value}/liveness/",
                },
                "AuditImagesLimit": 1,
            },
            ClientRequestToken=f"{tenant_id.value}-{ttl_seconds}",
        )
        session_id = str(response["SessionId"])
        return LivenessSession(
            provider_session_id=session_id,
            # El token del cliente lo emite el SDK de frontend contra esta
            # sesión; el backend solo entrega el identificador.
            client_token=session_id,
            expires_in_seconds=ttl_seconds,
            provider_id=self.PROVIDER_ID,
        )

    def get_result(
        self, tenant_id: TenantId, provider_session_id: str, *, threshold: float = 0.90
    ) -> LivenessResult:
        response = client("rekognition", self._settings.region).get_face_liveness_session_results(
            SessionId=provider_session_id
        )
        confidence = float(response.get("Confidence", 0.0)) / 100.0
        audited: ObjectRef | None = None
        images = response.get("AuditImages", [])
        if images:
            s3_object = images[0].get("S3Object", {})
            raise NotImplementedError(
                "Falta decidir cómo se obtiene el sha256 de la imagen auditada sin descargarla: "
                f"Rekognition la deja en {s3_object.get('Bucket', '?')} sin devolver el digest. "
                "Las opciones son descargar y calcular (coste de transferencia y de memoria en "
                "Lambda) o confiar en el ETag de S3, que no es sha256 para objetos multiparte. "
                "La invariante I6 exige un digest verificable."
            )
        return LivenessResult(
            score=confidence,
            threshold=threshold,
            passed=str(response.get("Status")) == "SUCCEEDED" and confidence >= threshold,
            injection_detected=False,
            audited_image=audited,
            provider_id=self.PROVIDER_ID,
            pad_level="iBeta-L2",
        )


__all__ = ["BedrockLlm", "RekognitionLiveness", "TextractOcr"]
