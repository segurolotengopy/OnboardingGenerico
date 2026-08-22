"""Capa criptográfica: solo biblioteca estándar, sin dependencias de nube."""

from __future__ import annotations

from .envelope import (
    Envelope,
    EnvelopeCipher,
    EnvelopeFieldCipher,
    LocalKeyProvider,
    SystemRandom,
    build_aad,
    shred_tenant_key,
)
from .field_policy import CryptoAction, FieldPolicy, apply_policy, default_policy
from .material_cache import AtomicMaterialCache, CachedKeyProvider, tenant_cache_key

__all__ = [
    "AtomicMaterialCache",
    "CachedKeyProvider",
    "CryptoAction",
    "Envelope",
    "EnvelopeCipher",
    "EnvelopeFieldCipher",
    "FieldPolicy",
    "LocalKeyProvider",
    "SystemRandom",
    "apply_policy",
    "build_aad",
    "default_policy",
    "shred_tenant_key",
    "tenant_cache_key",
]
