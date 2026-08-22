"""Adaptadores de AWS: implementación de referencia.

`boto3` se importa dentro de las funciones, de modo que importar este paquete
**no** falla sin el extra instalado. Instanciar un adaptador y usarlo sí exige
`pip install onboarding-generico[aws]`.
"""

from __future__ import annotations

from .ai import BedrockLlm, RekognitionLiveness, TextractOcr
from .orchestration import EventBridgeBus, StepFunctionsSaga
from .persistence import (
    DbEsdkFieldCipher,
    DynamoDbCapabilityRegistry,
    DynamoDbFlowSpecRepository,
    DynamoDbIdempotencyStore,
    DynamoDbMutexLock,
    DynamoDbSessionRepository,
    HierarchicalKeyProvider,
    S3ObjectStorage,
    SecretsManagerProvider,
)

__all__ = [
    "BedrockLlm",
    "DbEsdkFieldCipher",
    "DynamoDbCapabilityRegistry",
    "DynamoDbFlowSpecRepository",
    "DynamoDbIdempotencyStore",
    "DynamoDbMutexLock",
    "DynamoDbSessionRepository",
    "EventBridgeBus",
    "HierarchicalKeyProvider",
    "RekognitionLiveness",
    "S3ObjectStorage",
    "SecretsManagerProvider",
    "StepFunctionsSaga",
    "TextractOcr",
]
