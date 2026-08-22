"""Adaptadores en memoria: implementación completa de todos los puertos.

No requieren red ni dependencias externas. Son la referencia de comportamiento
que deben reproducir los adaptadores de AWS y GCP: la prueba de conformidad de
`tests/contract/` se ejecuta contra ellos.
"""

from __future__ import annotations

from .orchestration import (
    InMemoryEventBus,
    InMemoryHumanReview,
    InMemorySaga,
    InMemoryTelemetry,
)
from .providers import (
    InMemoryDocumentAlignment,
    InMemoryFaceMatch,
    InMemoryForgeryDetection,
    InMemoryLiveness,
    InMemoryLlm,
    InMemoryMrzReader,
    InMemoryOcrProvider,
)
from .repositories import (
    InMemoryCapabilityRegistry,
    InMemoryFlowSpecRepository,
    InMemoryIdempotencyStore,
    InMemoryMutexLock,
    InMemorySessionRepository,
)
from .security import (
    InMemoryAuthorizationProvider,
    InMemoryConfigProvider,
    InMemorySecretsProvider,
)
from .storage import InMemoryObjectStorage

__all__ = [
    "InMemoryAuthorizationProvider",
    "InMemoryCapabilityRegistry",
    "InMemoryConfigProvider",
    "InMemoryDocumentAlignment",
    "InMemoryEventBus",
    "InMemoryFaceMatch",
    "InMemoryFlowSpecRepository",
    "InMemoryForgeryDetection",
    "InMemoryHumanReview",
    "InMemoryIdempotencyStore",
    "InMemoryLiveness",
    "InMemoryLlm",
    "InMemoryMrzReader",
    "InMemoryMutexLock",
    "InMemoryObjectStorage",
    "InMemoryOcrProvider",
    "InMemorySaga",
    "InMemorySecretsProvider",
    "InMemorySessionRepository",
    "InMemoryTelemetry",
]
