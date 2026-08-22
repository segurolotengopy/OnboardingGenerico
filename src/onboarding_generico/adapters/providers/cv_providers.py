"""Proveedores de visión por computador: alineación, biometría facial y OCR local.

**Notas de licencia — leerlas antes de desplegar.**

- `fbieberly/document_warp` y `joellijo32/Document-Scanner-using-OpenCV` son
  **MIT** y sirven como código de referencia para la rectificación.
  `YegorCherov/document-scanner` **no tiene licencia**: todos los derechos
  reservados, no se usa.
- OpenCV se distribuye bajo **Apache-2.0** (versión 4.5.0 en adelante).
- **InsightFace**: el código es permisivo, pero los **pesos `buffalo_l`
  arrastran restricciones de uso no comercial independientes de la licencia
  del código**. Hay que licenciar los pesos aparte o entrenar propios.
- **TruFor**: los pesos también tienen restricción de uso no comercial.
- `minivision-ai/Silent-Face-Anti-Spoofing` es **Apache-2.0**, pero su modelo
  es de 2020 y **no se usa para liveness en producción**: PAD con modelos
  abiertos en un flujo KYC es riesgo regulatorio, no solo técnico.
- Tesseract es **Apache-2.0** y `pytesseract` **Apache-2.0**, pero el binario
  de Tesseract debe estar instalado en la imagen.

Todas las dependencias pesadas (`cv2`, `onnxruntime`, `numpy`, `pytesseract`)
se importan **dentro de los métodos**: importar este módulo no exige ninguna.

Nota de dimensionado: la memoria de una función Lambda va de **128 MB a
10.240 MB**. No existe requisito ligado a AVX-512 —la documentación de Lambda
solo cubre AVX2 y `arm64` usa NEON—, así que el dimensionado se decide por el
tamaño real del modelo y de la imagen, no por instrucciones vectoriales.
"""

from __future__ import annotations

from typing import Any, Sequence

from ...domain.value_objects import Confidence, ObjectRef, TenantId
from ...errors import MissingDependencyError
from ...ports.face_match import FaceMatchPort, FaceMatchResult
from ...ports.imaging import (
    AlignmentResult,
    DocumentAlignmentPort,
    ForgeryDetectionPort,
    ForgeryResult,
)
from ...ports.ocr import OcrPort, OcrResult, TextBlock

EXTRA_CV: str = "cv"


def _require(module_name: str, package_name: str, extra: str = EXTRA_CV) -> Any:
    import importlib  # noqa: PLC0415

    try:
        return importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise MissingDependencyError(package_name, extra) from exc


class OpenCvAlignment(DocumentAlignmentPort):
    """Rectificación de perspectiva y medida de calidad con OpenCV.

    Mide tres cosas que el paso de calidad necesita: nitidez (varianza del
    laplaciano), reflejo (proporción de píxeles saturados) y resolución
    efectiva del documento **ya recortado**, que es la que importa; la
    resolución de la foto completa no dice nada si el documento ocupa un
    cuarto del encuadre.
    """

    __slots__ = ("_storage",)

    PROVIDER_ID = "opencv_alignment"

    def __init__(self, storage: Any = None) -> None:
        self._storage = storage

    def align(self, tenant_id: TenantId, ref: ObjectRef, *, page: str = "FRONT") -> AlignmentResult:
        cv2 = _require("cv2", "opencv-python-headless")
        numpy = _require("numpy", "numpy")

        if self._storage is None:
            raise MissingDependencyError("object_storage", "core")
        raw = self._storage.get(tenant_id, ref)
        buffer = numpy.frombuffer(raw, dtype=numpy.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            return AlignmentResult(aligned=ref, detected=False, provider_id=self.PROVIDER_ID)

        grey = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        sharpness = float(cv2.Laplacian(grey, cv2.CV_64F).var())
        glare = float((grey > 245).sum()) / float(grey.size)

        edges = cv2.Canny(cv2.GaussianBlur(grey, (5, 5), 0), 60, 180)
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        quad = _largest_quadrilateral(cv2, contours)
        if quad is None:
            return AlignmentResult(
                aligned=ref,
                detected=False,
                sharpness=_normalize_sharpness(sharpness),
                glare=glare,
                resolution_px=int(min(image.shape[:2])),
                provider_id=self.PROVIDER_ID,
            )

        raise NotImplementedError(
            "Falta decidir la relación de aspecto de destino de la rectificación. ISO/IEC 7810 "
            "ID-1 (85,60 x 53,98 mm) sirve para la mayoría de las tarjetas, pero el pasaporte es "
            "ID-3 y varios documentos LATAM no cumplen ninguno de los dos. Forzar ID-1 a un "
            "documento que no lo es deforma el retrato y degrada la comparación facial, así que "
            "la relación tiene que venir del catálogo por país y tipo de documento."
        )


class InsightFaceMatch(FaceMatchPort):
    """Comparación facial 1:1 con InsightFace sobre ONNX Runtime.

    Umbrales de referencia (SP 800-63A-4, operación 1:1): FMR objetivo
    ≤ 1:10.000 y FNMR objetivo ≤ 1:100. El umbral de similitud se calibra por
    población: un umbral tomado de un benchmark ajeno produce tasas reales
    distintas de las declaradas.

    **Los pesos `buffalo_l` tienen restricción de uso no comercial** que es
    independiente de la licencia del código. Verificar la licencia de los
    pesos antes de desplegar.
    """

    __slots__ = ("_storage", "_model_path", "_session")

    PROVIDER_ID = "insightface_match"

    def __init__(self, storage: Any = None, model_path: str = "") -> None:
        self._storage = storage
        self._model_path = model_path
        self._session: Any = None

    def _load(self) -> Any:
        if self._session is not None:
            return self._session
        onnxruntime = _require("onnxruntime", "onnxruntime")
        if not self._model_path:
            raise MissingDependencyError("modelo de reconocimiento facial", EXTRA_CV)
        self._session = onnxruntime.InferenceSession(
            self._model_path, providers=["CPUExecutionProvider"]
        )
        return self._session

    def compare(
        self,
        tenant_id: TenantId,
        reference: ObjectRef,
        candidate: ObjectRef,
        *,
        threshold: float = 0.82,
    ) -> FaceMatchResult:
        numpy = _require("numpy", "numpy")
        session = self._load()
        left = self._embed(session, numpy, tenant_id, reference)
        right = self._embed(session, numpy, tenant_id, candidate)
        similarity = float(
            numpy.dot(left, right) / (numpy.linalg.norm(left) * numpy.linalg.norm(right))
        )
        # El coseno vive en [-1, 1] y el umbral del dominio en [0, 1].
        normalized = (similarity + 1.0) / 2.0
        return FaceMatchResult(
            similarity=normalized,
            threshold=threshold,
            matched=normalized >= threshold,
            provider_id=self.PROVIDER_ID,
            model_version=self._model_path.rsplit("/", 1)[-1] or "unknown",
            quality_reference=self.assess_quality(tenant_id, reference),
            quality_candidate=self.assess_quality(tenant_id, candidate),
        )

    def _embed(self, session: Any, numpy: Any, tenant_id: TenantId, ref: ObjectRef) -> Any:
        cv2 = _require("cv2", "opencv-python-headless")
        raw = self._storage.get(tenant_id, ref)
        image = cv2.imdecode(numpy.frombuffer(raw, dtype=numpy.uint8), cv2.IMREAD_COLOR)
        resized = cv2.resize(image, (112, 112))
        tensor = ((resized.astype("float32") - 127.5) / 128.0).transpose(2, 0, 1)[None, ...]
        outputs = session.run(None, {session.get_inputs()[0].name: tensor})
        return numpy.asarray(outputs[0][0])

    def assess_quality(self, tenant_id: TenantId, ref: ObjectRef) -> float:
        raise NotImplementedError(
            "Falta decidir el conjunto de métricas de calidad facial y su ponderación. "
            "ISO/IEC 39794-5 define atributos (pose, iluminación, oclusión, nitidez, resolución "
            "interpupilar) pero no una fórmula única de calidad; el peso relativo de cada uno "
            "depende del modelo de comparación que se use después, así que la calibración es una "
            "decisión conjunta de producto y de riesgo."
        )


class TruForForgery(ForgeryDetectionPort):
    """Detección de manipulación documental.

    **Los pesos de TruFor tienen restricción de uso no comercial**, igual que
    los de InsightFace. Alternativa sin esa restricción: análisis clásico
    (nivel de error de compresión, discontinuidades de ruido, coherencia de
    metadatos EXIF), con menor sensibilidad pero sin problema de licencia.
    """

    __slots__ = ("_storage", "_model_path")

    PROVIDER_ID = "trufor_forgery"

    def __init__(self, storage: Any = None, model_path: str = "") -> None:
        self._storage = storage
        self._model_path = model_path

    def analyze(
        self, tenant_id: TenantId, ref: ObjectRef, *, threshold: float = 0.30
    ) -> ForgeryResult:
        raise NotImplementedError(
            "Falta decidir el modelo de detección y, con él, su licencia. Con pesos de TruFor hay "
            "restricción de uso no comercial que bloquea el despliegue del producto; con análisis "
            "clásico (ELA, ruido, EXIF) no hay restricción pero la sensibilidad cae y el umbral de "
            "derivación a revisión humana tiene que subir. Es una decisión de producto y legal, no "
            "de implementación."
        )


class TesseractOcr(OcrPort):
    """OCR local con Tesseract.

    Licencia: Tesseract y `pytesseract` son **Apache-2.0**, pero el binario de
    Tesseract debe estar en la imagen del contenedor. Se usa como último
    recurso de la cadena de reserva: su precisión sobre documentos de
    identidad con fondos de seguridad es sensiblemente peor que la de los
    servicios gestionados, y por eso no es proveedor primario.
    """

    __slots__ = ("_storage", "_languages")

    PROVIDER_ID = "tesseract_ocr"

    def __init__(self, storage: Any = None, languages: str = "spa+eng") -> None:
        self._storage = storage
        self._languages = languages

    def detect_text(
        self,
        tenant_id: TenantId,
        ref: ObjectRef,
        *,
        page: str = "FRONT",
        languages: Sequence[str] = (),
    ) -> OcrResult:
        pytesseract = _require("pytesseract", "pytesseract")
        pillow = _require("PIL.Image", "pillow")
        import io  # noqa: PLC0415

        raw = self._storage.get(tenant_id, ref)
        image = pillow.open(io.BytesIO(raw))
        data = pytesseract.image_to_data(
            image,
            lang="+".join(languages) if languages else self._languages,
            output_type=pytesseract.Output.DICT,
        )
        blocks: list[TextBlock] = []
        for index, text in enumerate(data.get("text", [])):
            stripped = str(text).strip()
            if not stripped:
                continue
            confidence = float(data["conf"][index])
            if confidence < 0:
                continue
            blocks.append(
                TextBlock(
                    text=stripped, confidence=Confidence(confidence / 100.0), block_type="WORD"
                )
            )
        return OcrResult(
            blocks=tuple(blocks),
            provider_id=self.PROVIDER_ID,
            page=page,
            language=self._languages,
            warnings=("proveedor de último recurso: precisión inferior a la de los gestionados",),
        )


def _largest_quadrilateral(cv2: Any, contours: Any) -> Any:
    """Mayor contorno de cuatro vértices, candidato al borde del documento."""
    best = None
    best_area = 0.0
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) != 4:
            continue
        area = float(cv2.contourArea(approx))
        if area > best_area:
            best, best_area = approx, area
    return best


def _normalize_sharpness(laplacian_variance: float) -> float:
    """Lleva la varianza del laplaciano al intervalo [0, 1].

    El divisor de 500 es el valor por encima del cual, en pruebas internas
    sobre capturas de móvil, la nitidez deja de limitar al OCR. Es un
    parámetro de calibración, no una constante universal.
    """
    return min(1.0, laplacian_variance / 500.0)


__all__ = [
    "EXTRA_CV",
    "InsightFaceMatch",
    "OpenCvAlignment",
    "TesseractOcr",
    "TruForForgery",
]
