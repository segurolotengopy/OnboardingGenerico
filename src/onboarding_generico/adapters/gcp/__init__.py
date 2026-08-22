"""Adaptadores de GCP: alternativa por adaptadores.

Los paquetes `google-cloud-*` se importan dentro de las funciones, de modo que
importar este paquete no falla sin el extra instalado. Usar un adaptador sí
exige `pip install onboarding-generico[gcp]`.
"""

from __future__ import annotations

from .ai import ClaudeOnVertexLlm, DocumentAiOcr
from .orchestration import CloudWorkflowsSaga, PubSubBus
from .persistence import (
    FirestoreCapabilityRegistry,
    FirestoreFlowSpecRepository,
    FirestoreIdempotencyStore,
    FirestoreMutexLock,
    FirestoreSessionRepository,
    GcsObjectStorage,
    SecretManagerProvider,
    TinkFieldCipher,
    TinkKeyProvider,
)

__all__ = [
    "ClaudeOnVertexLlm",
    "CloudWorkflowsSaga",
    "DocumentAiOcr",
    "FirestoreCapabilityRegistry",
    "FirestoreFlowSpecRepository",
    "FirestoreIdempotencyStore",
    "FirestoreMutexLock",
    "FirestoreSessionRepository",
    "GcsObjectStorage",
    "PubSubBus",
    "SecretManagerProvider",
    "TinkFieldCipher",
    "TinkKeyProvider",
]
