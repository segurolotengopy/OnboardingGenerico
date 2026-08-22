"""Puertos del hexágono.

Clasificación de los puertos según la referencia de paridad GCP §4:

1. **Se portan sin fricción** (interfaz libre): `ObjectStorage`, `LlmPort`,
   `TelemetryPort`.
2. **GCP dicta la forma** (si la dictara AWS, el adaptador GCP quedaría
   inseguro o inviable): `SessionRepository` y `CapabilityRegistryRepository`
   (sin primitivas PK/SK), `AuthorizationProvider` (autorización en el núcleo,
   no en el gateway) y `OnboardingSagaPort` (sin depender de esperas > 12 h en
   un único callback).
3. **Se construyen a medida en ambas nubes** para eliminar la asimetría en vez
   de gestionarla: `HumanReviewPort`, `LivenessPort` (vía SaaS único) y
   `ConfigProvider`.
"""

from __future__ import annotations

from .config_port import AuthorizationProvider, ConfigProvider
from .crypto import FieldCipher, KeyProvider, MaterialCache, SecureRandom
from .events_bus import EventBusPort, IntegrationEvent
from .face_match import FaceMatchPort, FaceMatchResult
from .human_review import HumanReviewPort, ReviewCase, ReviewResolution
from .imaging import (
    AlignmentResult,
    DocumentAlignmentPort,
    ForgeryDetectionPort,
    ForgeryResult,
)
from .liveness import LivenessPort, LivenessResult, LivenessSession
from .llm import ExtractionResult, LlmPort, LlmUsage
from .mrz_reader import MrzReaderPort
from .object_storage import ObjectStorage
from .ocr import BoundingBox, OcrPort, OcrResult, TextBlock
from .repository import (
    CapabilityRegistryRepository,
    FlowSpecRepository,
    IdempotencyStore,
    MutexLock,
    SessionRepository,
)
from .saga import OnboardingSagaPort, ResumeToken, SagaHandle, SagaStatus
from .secrets import SecretsProvider
from .telemetry import TelemetryPort

#: Todos los puertos abstractos. Lo consume la prueba de conformidad.
ALL_PORTS: tuple[type, ...] = (
    AuthorizationProvider,
    CapabilityRegistryRepository,
    ConfigProvider,
    DocumentAlignmentPort,
    EventBusPort,
    FaceMatchPort,
    FieldCipher,
    FlowSpecRepository,
    ForgeryDetectionPort,
    HumanReviewPort,
    IdempotencyStore,
    KeyProvider,
    LivenessPort,
    LlmPort,
    MaterialCache,
    MrzReaderPort,
    MutexLock,
    ObjectStorage,
    OcrPort,
    OnboardingSagaPort,
    SecretsProvider,
    SecureRandom,
    SessionRepository,
    TelemetryPort,
)

__all__ = [
    "ALL_PORTS",
    "AlignmentResult",
    "AuthorizationProvider",
    "BoundingBox",
    "CapabilityRegistryRepository",
    "ConfigProvider",
    "DocumentAlignmentPort",
    "EventBusPort",
    "ExtractionResult",
    "FaceMatchPort",
    "FaceMatchResult",
    "FieldCipher",
    "FlowSpecRepository",
    "ForgeryDetectionPort",
    "ForgeryResult",
    "HumanReviewPort",
    "IdempotencyStore",
    "IntegrationEvent",
    "KeyProvider",
    "LivenessPort",
    "LivenessResult",
    "LivenessSession",
    "LlmPort",
    "LlmUsage",
    "MaterialCache",
    "MrzReaderPort",
    "MutexLock",
    "ObjectStorage",
    "OcrPort",
    "OcrResult",
    "OnboardingSagaPort",
    "ResumeToken",
    "ReviewCase",
    "ReviewResolution",
    "SagaHandle",
    "SagaStatus",
    "SecretsProvider",
    "SecureRandom",
    "SessionRepository",
    "TelemetryPort",
    "TextBlock",
]
