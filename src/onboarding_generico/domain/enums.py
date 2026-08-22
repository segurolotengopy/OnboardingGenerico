"""Enumeraciones del dominio.

Todos los valores son cadenas estables: se persisten, viajan por la API y
aparecen en el log de auditoría. Renombrar un valor es un cambio incompatible.
"""

from __future__ import annotations

import enum


class StrEnum(enum.StrEnum):
    """Base de enumeración textual del dominio.

    Deriva de `enum.StrEnum` (disponible desde Python 3.11, que es el mínimo
    del proyecto). Se conserva el alias propio para no reescribir los imports
    de todo el dominio y para tener un punto único donde ajustar el
    comportamiento de serialización si hiciera falta. `enum.StrEnum` ya
    garantiza que `str(miembro)` y `json.dumps` produzcan el valor, que es lo
    que la mezcla manual `(str, Enum)` buscaba.
    """


class Capability(StrEnum):
    """Capacidades del catálogo. El identificador incluye la versión mayor."""

    CAPTURE_QUALITY = "capture.quality.v1"
    DOCUMENT_ALIGNMENT = "document.alignment.v1"
    OCR_DOCUMENT = "ocr.document.v1"
    MRZ_PARSE = "mrz.parse.v1"
    EXTRACTION_SEMANTIC = "extraction.semantic.v1"
    VALIDATION_CROSSFIELD = "validation.crossfield.v1"
    FORGERY_DETECTION = "forgery.detection.v1"
    BIOMETRICS_LIVENESS = "biometrics.liveness.v2"
    BIOMETRICS_FACEMATCH = "biometrics.facematch.v1"
    REGISTRY_VERIFY = "registry.verify.v1"
    AML_SCREENING = "aml.screening.v1"
    HUMAN_REVIEW = "review.human.v1"
    NOTIFY_WEBHOOK = "notify.webhook.v1"


class ProviderKind(StrEnum):
    """Naturaleza del proveedor que implementa una capacidad."""

    MANAGED_AWS = "MANAGED_AWS"
    MANAGED_GCP = "MANAGED_GCP"
    SAAS_THIRD_PARTY = "SAAS_THIRD_PARTY"
    OPEN_SOURCE_LOCAL = "OPEN_SOURCE_LOCAL"
    LLM_MULTIMODAL = "LLM_MULTIMODAL"
    INTERNAL = "INTERNAL"


class SessionState(StrEnum):
    """Estados de la sesión de onboarding (doc 03 §3)."""

    CREATED = "CREATED"
    COLLECTING = "COLLECTING"
    PROCESSING = "PROCESSING"
    AWAITING_SUBJECT = "AWAITING_SUBJECT"
    PENDING_REVIEW = "PENDING_REVIEW"
    IN_REVIEW = "IN_REVIEW"
    DECIDED = "DECIDED"
    RETAINED = "RETAINED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    ABANDONED = "ABANDONED"
    CANCELLED = "CANCELLED"
    PURGED = "PURGED"


class StepState(StrEnum):
    """Estados de un paso dentro de la sesión (doc 03 §3.2).

    `NEGATIVE` es terminal y **exitoso desde el punto de vista del pipeline**:
    el paso hizo su trabajo y la respuesta fue "no coincide". Modelarlo como
    `FAILED` provocaría reintentos inútiles contra proveedores facturables.
    """

    PENDING = "PENDING"
    READY = "READY"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    FALLBACK = "FALLBACK"
    SUCCEEDED = "SUCCEEDED"
    NEGATIVE = "NEGATIVE"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class DecisionOutcome(StrEnum):
    """Veredicto de la sesión."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    SIGNALS_ONLY = "SIGNALS_ONLY"
    INCONCLUSIVE = "INCONCLUSIVE"


class DecisionIssuer(StrEnum):
    """Quién emite el veredicto (doc 04 §4.3), con consecuencias legales.

    `SIGNALS_ONLY` es obligatorio en Bolivia: el art. 32(II) del Instructivo
    UIF prohíbe delegar en terceros la ejecución de la Debida Diligencia.
    """

    MIDDLEWARE = "MIDDLEWARE"
    SIGNALS_ONLY = "SIGNALS_ONLY"
    REQUESTER_CONFIRMS = "REQUESTER_CONFIRMS"


class DecisionSource(StrEnum):
    """Origen material de la decisión."""

    AUTOMATED_POLICY = "AUTOMATED_POLICY"
    HUMAN_REVIEWER = "HUMAN_REVIEWER"
    REQUESTER = "REQUESTER"
    SYSTEM_TIMEOUT = "SYSTEM_TIMEOUT"


class DocumentType(StrEnum):
    """Tipos de documento soportados por el catálogo."""

    PASSPORT = "PASSPORT"
    ID_CARD = "ID_CARD"
    RESIDENCE_PERMIT = "RESIDENCE_PERMIT"
    DRIVING_LICENSE = "DRIVING_LICENSE"
    INE_2019 = "INE_2019"
    INE_2021 = "INE_2021"
    CI_BO = "CI_BO"
    CI_PY = "CI_PY"
    UNKNOWN = "UNKNOWN"


class MrzFormat(StrEnum):
    """Formatos de zona de lectura mecánica de ICAO Doc 9303."""

    TD1 = "TD1"
    TD2 = "TD2"
    TD3 = "TD3"


class EvidenceKind(StrEnum):
    """Clase de evidencia producida por un paso."""

    CAPTURE_QUALITY = "CAPTURE_QUALITY"
    DOCUMENT_ALIGNMENT = "DOCUMENT_ALIGNMENT"
    OCR = "OCR"
    MRZ = "MRZ"
    SEMANTIC_EXTRACTION = "SEMANTIC_EXTRACTION"
    CROSS_FIELD = "CROSS_FIELD"
    FORGERY = "FORGERY"
    LIVENESS = "LIVENESS"
    FACE_MATCH = "FACE_MATCH"
    REGISTRY = "REGISTRY"
    AML = "AML"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class Verdict(StrEnum):
    """Resultado de una evidencia individual."""

    PASS = "PASS"  # noqa: S105 - veredicto de una evidencia, no una contraseña
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RiskLevel(StrEnum):
    """Nivel de riesgo agregado, alineado con el enfoque basado en riesgo (GAFI R.1)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PROHIBITED = "PROHIBITED"

    @property
    def rank(self) -> int:
        return _RISK_RANK[self]


_RISK_RANK: dict[RiskLevel, int] = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.PROHIBITED: 3,
}


class DataClass(StrEnum):
    """Clasificación del dato, que gobierna retención y purga."""

    DOCUMENT = "DOCUMENT"
    BIOMETRIC = "BIOMETRIC"
    DERIVED = "DERIVED"
    METADATA = "METADATA"


class ArtifactSlot(StrEnum):
    """Ranuras de artefacto que el requirente debe llenar."""

    DOC_FRONT = "DOC_FRONT"
    DOC_BACK = "DOC_BACK"
    SELFIE = "SELFIE"
    LIVENESS_VIDEO = "LIVENESS_VIDEO"
    PROOF_OF_ADDRESS = "PROOF_OF_ADDRESS"


class OnFailure(StrEnum):
    """Qué hacer cuando un paso falla."""

    ABORT = "ABORT"
    REQUEST_RECAPTURE = "REQUEST_RECAPTURE"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    CONTINUE = "CONTINUE"


class WaitClass(StrEnum):
    """Clase de espera del paso; determina el reparto padre/hijo al compilar."""

    NONE = "NONE"
    SHORT = "SHORT"
    LONG = "LONG"


class CompileTarget(StrEnum):
    """Destinos de compilación del plan de ejecución."""

    ASL = "ASL"
    CLOUD_WORKFLOWS = "CLOUD_WORKFLOWS"


class Sex(StrEnum):
    """Sexo tal y como lo codifica ICAO 9303 (`M`, `F`, `<` = no especificado)."""

    MALE = "M"
    FEMALE = "F"
    UNSPECIFIED = "X"


class EventType(StrEnum):
    """Tipos de evento del log de auditoría append-only."""

    SESSION_CREATED = "SESSION_CREATED"
    SESSION_STATE_CHANGED = "SESSION_STATE_CHANGED"
    ARTIFACT_REGISTERED = "ARTIFACT_REGISTERED"
    STEP_STARTED = "STEP_STARTED"
    STEP_COMPLETED = "STEP_COMPLETED"
    EVIDENCE_SEALED = "EVIDENCE_SEALED"
    DECISION_ISSUED = "DECISION_ISSUED"
    REVIEW_OPENED = "REVIEW_OPENED"
    REVIEW_RESOLVED = "REVIEW_RESOLVED"
    RETENTION_APPLIED = "RETENTION_APPLIED"
    PURGE_REQUESTED = "PURGE_REQUESTED"
    PURGE_COMPLETED = "PURGE_COMPLETED"
    KEY_DESTROYED = "KEY_DESTROYED"
    POLICY_VIOLATION = "POLICY_VIOLATION"


__all__ = [
    "ArtifactSlot",
    "Capability",
    "CompileTarget",
    "DataClass",
    "DecisionIssuer",
    "DecisionOutcome",
    "DecisionSource",
    "DocumentType",
    "EventType",
    "EvidenceKind",
    "MrzFormat",
    "OnFailure",
    "ProviderKind",
    "RiskLevel",
    "SessionState",
    "Sex",
    "StepState",
    "StrEnum",
    "Verdict",
    "WaitClass",
]
