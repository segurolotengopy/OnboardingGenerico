"""Proveedores de capacidad en memoria: OCR, MRZ, alineación, biometría y LLM.

No simulan visión por computador: producen resultados **deterministas y
programables**, que es lo que hace útil a un doble de prueba. Las respuestas
se guionizan por `ObjectRef` o por sesión, de modo que una prueba puede
construir el escenario exacto que quiere ejercitar (banda gris, inyección
detectada, OCR de baja confianza) sin depender de una imagen real.

El lector de MRZ **sí es real**: delega en `domain.mrz`, que implementa el
algoritmo 7-3-1 de ICAO 9303. Solo la localización de la MRZ en la imagen está
simulada; el parseo y la verificación son los de producción.
"""

from __future__ import annotations

import threading
from typing import Any, Mapping, Sequence

from ...domain.enums import MrzFormat
from ...domain.mrz import MrzRecord, normalize_lines, parse_mrz
from ...domain.value_objects import Confidence, ObjectRef, TenantId
from ...errors import MrzParseError, ProviderUnavailableError
from ...ports.face_match import FaceMatchPort, FaceMatchResult
from ...ports.imaging import (
    AlignmentResult,
    DocumentAlignmentPort,
    ForgeryDetectionPort,
    ForgeryResult,
)
from ...ports.liveness import LivenessPort, LivenessResult, LivenessSession
from ...ports.llm import ExtractionResult, LlmPort, LlmUsage
from ...ports.mrz_reader import MrzReaderPort
from ...ports.ocr import BoundingBox, OcrPort, OcrResult, TextBlock


class InMemoryOcrProvider(OcrPort):
    """OCR guionizado: devuelve el texto que la prueba haya asociado al objeto."""

    __slots__ = ("_scripts", "_default_text", "_lock", "provider_id", "unavailable")

    def __init__(self, provider_id: str = "inmemory_ocr", default_text: str = "") -> None:
        self.provider_id = provider_id
        self._scripts: dict[str, tuple[str, float]] = {}
        self._default_text = default_text
        self._lock = threading.Lock()
        self.unavailable = False

    def script(self, ref: ObjectRef, text: str, *, confidence: float = 0.97) -> None:
        """Asocia un texto a un objeto concreto."""
        with self._lock:
            self._scripts[ref.key] = (text, confidence)

    def detect_text(
        self,
        tenant_id: TenantId,
        ref: ObjectRef,
        *,
        page: str = "FRONT",
        languages: Sequence[str] = (),
    ) -> OcrResult:
        if self.unavailable:
            raise ProviderUnavailableError(
                "el proveedor de OCR no responde", provider_id=self.provider_id
            )
        with self._lock:
            text, confidence = self._scripts.get(ref.key, (self._default_text, 0.55))
        lines = [line for line in text.split("\n") if line]
        blocks = tuple(
            TextBlock(
                text=line,
                confidence=Confidence(confidence),
                box=BoundingBox(left=0.05, top=0.05 + index * 0.05, width=0.9, height=0.04),
                block_type="LINE",
            )
            for index, line in enumerate(lines)
        )
        return OcrResult(
            blocks=blocks,
            provider_id=self.provider_id,
            page=page,
            language=languages[0] if languages else "spa",
        )


class InMemoryMrzReader(MrzReaderPort):
    """Lector de MRZ que usa el parser real del dominio.

    La localización en la imagen se emula asociando el texto de la MRZ al
    objeto; el parseo, la verificación 7-3-1 y el dígito compuesto son los de
    `domain.mrz`, sin atajos.
    """

    __slots__ = ("_scripts", "_lock")

    def __init__(self) -> None:
        self._scripts: dict[str, str] = {}
        self._lock = threading.Lock()

    def script(self, ref: ObjectRef, mrz_text: str) -> None:
        with self._lock:
            self._scripts[ref.key] = mrz_text

    def read(
        self,
        tenant_id: TenantId,
        ref: ObjectRef,
        *,
        expected_format: MrzFormat | None = None,
    ) -> MrzRecord:
        with self._lock:
            text = self._scripts.get(ref.key)
        if text is None:
            raise MrzParseError("no se localizó una MRZ en la imagen", key=ref.key)
        return self.read_text(text, expected_format=expected_format)

    def read_text(self, text: str, *, expected_format: MrzFormat | None = None) -> MrzRecord:
        # `strict=False`: un dígito de control incorrecto no descarta la
        # lectura, se reporta para que el motor de decisión derive a revisión.
        return parse_mrz(normalize_lines(text), expected_format=expected_format, strict=False)


class InMemoryDocumentAlignment(DocumentAlignmentPort):
    """Alineación guionizada con umbrales de calidad configurables."""

    __slots__ = ("_scripts", "_lock", "provider_id", "default_quality")

    def __init__(self, provider_id: str = "inmemory_alignment") -> None:
        self.provider_id = provider_id
        self._scripts: dict[str, AlignmentResult] = {}
        self._lock = threading.Lock()
        self.default_quality = {"sharpness": 0.82, "glare": 0.11, "resolution_px": 1600}

    def script(self, ref: ObjectRef, result: AlignmentResult) -> None:
        with self._lock:
            self._scripts[ref.key] = result

    def align(self, tenant_id: TenantId, ref: ObjectRef, *, page: str = "FRONT") -> AlignmentResult:
        with self._lock:
            scripted = self._scripts.get(ref.key)
        if scripted is not None:
            return scripted
        return AlignmentResult(
            aligned=ref,
            detected=True,
            sharpness=float(self.default_quality["sharpness"]),
            glare=float(self.default_quality["glare"]),
            resolution_px=int(self.default_quality["resolution_px"]),
            skew_degrees=0.4,
            provider_id=self.provider_id,
        )


class InMemoryForgeryDetection(ForgeryDetectionPort):
    """Detección de manipulación guionizada."""

    __slots__ = ("_scores", "_lock", "provider_id")

    def __init__(self, provider_id: str = "inmemory_forgery") -> None:
        self.provider_id = provider_id
        self._scores: dict[str, tuple[float, tuple[str, ...]]] = {}
        self._lock = threading.Lock()

    def script(self, ref: ObjectRef, score: float, signals: Sequence[str] = ()) -> None:
        with self._lock:
            self._scores[ref.key] = (score, tuple(signals))

    def analyze(
        self, tenant_id: TenantId, ref: ObjectRef, *, threshold: float = 0.30
    ) -> ForgeryResult:
        with self._lock:
            score, signals = self._scores.get(ref.key, (0.04, ()))
        return ForgeryResult(
            forgery_score=score,
            threshold=threshold,
            suspicious=score > threshold,
            signals=signals,
            provider_id=self.provider_id,
        )


class InMemoryFaceMatch(FaceMatchPort):
    """Comparación facial guionizada por par (referencia, candidato)."""

    __slots__ = ("_pairs", "_quality", "_lock", "provider_id", "default_similarity")

    def __init__(self, provider_id: str = "inmemory_facematch", default_similarity: float = 0.91) -> None:
        self.provider_id = provider_id
        self.default_similarity = default_similarity
        self._pairs: dict[tuple[str, str], float] = {}
        self._quality: dict[str, float] = {}
        self._lock = threading.Lock()

    def script(self, reference: ObjectRef, candidate: ObjectRef, similarity: float) -> None:
        with self._lock:
            self._pairs[(reference.key, candidate.key)] = similarity

    def script_quality(self, ref: ObjectRef, quality: float) -> None:
        with self._lock:
            self._quality[ref.key] = quality

    def compare(
        self,
        tenant_id: TenantId,
        reference: ObjectRef,
        candidate: ObjectRef,
        *,
        threshold: float = 0.82,
    ) -> FaceMatchResult:
        with self._lock:
            similarity = self._pairs.get((reference.key, candidate.key), self.default_similarity)
            quality_reference = self._quality.get(reference.key, 0.90)
            quality_candidate = self._quality.get(candidate.key, 0.90)
        return FaceMatchResult(
            similarity=similarity,
            threshold=threshold,
            matched=similarity >= threshold,
            provider_id=self.provider_id,
            model_version="inmemory-1.0",
            quality_reference=quality_reference,
            quality_candidate=quality_candidate,
        )

    def assess_quality(self, tenant_id: TenantId, ref: ObjectRef) -> float:
        with self._lock:
            return self._quality.get(ref.key, 0.90)


class InMemoryLiveness(LivenessPort):
    """Liveness guionizado.

    Recordatorio de diseño: en producción este puerto lo cubre un SaaS con
    certificación iBeta en **ambas** nubes, porque GCP no ofrece liveness
    gestionado y construirlo con modelos abiertos es riesgo regulatorio.
    """

    __slots__ = ("_results", "_sessions", "_lock", "provider_id", "default_score", "_counter")

    def __init__(self, provider_id: str = "inmemory_liveness", default_score: float = 0.96) -> None:
        self.provider_id = provider_id
        self.default_score = default_score
        self._results: dict[str, tuple[float, bool, ObjectRef | None]] = {}
        self._sessions: dict[str, str] = {}
        self._lock = threading.Lock()
        self._counter = 0

    def script(
        self,
        provider_session_id: str,
        *,
        score: float,
        injection_detected: bool = False,
        audited_image: ObjectRef | None = None,
    ) -> None:
        with self._lock:
            self._results[provider_session_id] = (score, injection_detected, audited_image)

    def create_session(self, tenant_id: TenantId, *, ttl_seconds: int = 300) -> LivenessSession:
        with self._lock:
            self._counter += 1
            provider_session_id = f"liv-{tenant_id.value}-{self._counter}"
            self._sessions[provider_session_id] = tenant_id.value
        return LivenessSession(
            provider_session_id=provider_session_id,
            client_token=f"token-{provider_session_id}",
            expires_in_seconds=ttl_seconds,
            provider_id=self.provider_id,
        )

    def get_result(
        self, tenant_id: TenantId, provider_session_id: str, *, threshold: float = 0.90
    ) -> LivenessResult:
        with self._lock:
            owner = self._sessions.get(provider_session_id)
            score, injection, audited = self._results.get(
                provider_session_id, (self.default_score, False, None)
            )
        if owner is not None and owner != tenant_id.value:
            raise ProviderUnavailableError(
                "la sesión de liveness pertenece a otro tenant", provider_id=self.provider_id
            )
        return LivenessResult(
            score=score,
            threshold=threshold,
            passed=score >= threshold and not injection,
            injection_detected=injection,
            audited_image=audited,
            provider_id=self.provider_id,
            pad_level="iBeta-L2",
        )


class InMemoryLlm(LlmPort):
    """LLM guionizado que valida la salida contra el esquema declarado."""

    __slots__ = ("_responses", "_lock", "provider_id", "model_id", "calls")

    def __init__(self, provider_id: str = "inmemory_llm", model_id: str = "claude-inmemory") -> None:
        self.provider_id = provider_id
        self.model_id = model_id
        self._responses: dict[str, tuple[dict[str, Any], dict[str, float]]] = {}
        self._lock = threading.Lock()
        self.calls: list[dict[str, Any]] = []

    def script(
        self, template: str, data: Mapping[str, Any], field_confidence: Mapping[str, float] | None = None
    ) -> None:
        with self._lock:
            self._responses[template] = (dict(data), dict(field_confidence or {}))

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
        with self._lock:
            data, field_confidence = self._responses.get(template, ({}, {}))
            # Se registra solo metadata: el prompt puede llevar PII.
            self.calls.append(
                {
                    "tenant_id": tenant_id.value,
                    "template": template,
                    "image_count": len(image_refs),
                    "prompt_length": len(prompt),
                    "prompt_cache": enable_prompt_cache,
                }
            )
        allowed = set(schema.get("properties", {}).keys()) if "properties" in schema else set(data)
        filtered = {k: v for k, v in data.items() if not allowed or k in allowed}
        confidences = field_confidence or {k: 0.93 for k in filtered}
        overall = min(confidences.values()) if confidences else 0.0
        return ExtractionResult(
            data=filtered,
            confidence=Confidence(overall),
            field_confidence=confidences,
            usage=LlmUsage(
                input_tokens=len(prompt) // 4,
                output_tokens=64,
                cached_input_tokens=len(prompt) // 8 if enable_prompt_cache else 0,
            ),
            provider_id=self.provider_id,
            model_id=self.model_id,
        )


__all__ = [
    "InMemoryDocumentAlignment",
    "InMemoryFaceMatch",
    "InMemoryForgeryDetection",
    "InMemoryLiveness",
    "InMemoryLlm",
    "InMemoryMrzReader",
    "InMemoryOcrProvider",
]
