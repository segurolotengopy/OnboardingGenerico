"""Caché de material criptográfico con **carga atómica por clave**.

Por qué NO se usa `CachingCryptoMaterialsManager`
--------------------------------------------------

El caso público que reporta un **77 % de reducción del coste de KMS** (NICE
Actimize) es real, pero **no se consiguió con `CachingCryptoMaterialsManager`**:
el artículo describe al CCMM como *la causa* del problema, no como su
solución. Con CCMM, en un proceso multihilo, cuando la entrada cacheada
expira **todos los hilos fallan el acceso a la vez** y todos llaman a KMS: es
un *cache stampede* clásico. El resultado es un pico de llamadas justo en el
momento de mayor carga, exactamente lo contrario de lo que se buscaba.

Las dos soluciones correctas son:

1. El **hierarchical keyring** (recomendación explícita de AWS), que mantiene
   *branch keys* en una tabla propia y reduce las llamadas a KMS a una por
   rotación de branch key.
2. Una **caché con carga atómica por clave**, que es lo que implementa este
   módulo: al fallar, un único hilo carga y los demás esperan a ese resultado
   en vez de disparar cargas paralelas.

En GCP el problema es más agudo: **Tink no trae caché de material
criptográfico integrado** y sin ella la latencia de KMS por operación hace
inviable el sistema. Esta clase cubre ambas nubes.

Garantía que ofrece esta implementación
---------------------------------------

Para una clave dada, `loads <= misses` y, ante N hilos concurrentes que fallan
a la vez sobre la misma clave, `loads == 1`. La prueba unitaria lo verifica
con hilos reales y un cargador lento.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Generic, Iterator, Mapping, TypeVar

from ..ports.crypto import MaterialCache

T = TypeVar("T")

Clock = Callable[[], float]


@dataclass(slots=True)
class _Entry(Generic[T]):
    """Entrada de la caché con su instante de expiración."""

    value: T
    expires_at: float

    def is_expired(self, now: float) -> bool:
        return now >= self.expires_at


class AtomicMaterialCache(MaterialCache, Generic[T]):
    """Caché TTL con un cerrojo por clave.

    El cerrojo global protege únicamente el diccionario; la **carga** se hace
    bajo un cerrojo específico de la clave, de modo que cargar material del
    tenant A no bloquea al tenant B. Esa distinción es la que evita convertir
    la caché en un cuello de botella global.
    """

    __slots__ = ("_ttl", "_max_entries", "_clock", "_entries", "_global_lock", "_key_locks", "_stats")

    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        max_entries: int = 512,
        clock: Clock | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds debe ser positivo")
        if max_entries <= 0:
            raise ValueError("max_entries debe ser positivo")
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock: Clock = clock or time.monotonic
        self._entries: dict[str, _Entry[T]] = {}
        self._global_lock = threading.Lock()
        self._key_locks: dict[str, threading.Lock] = {}
        self._stats = {"hits": 0, "misses": 0, "loads": 0, "evictions": 0, "expirations": 0}

    # -- API del puerto ----------------------------------------------------

    def get_or_load(self, key: str, loader: Callable[[], T]) -> T:  # type: ignore[override]
        """Devuelve el valor cacheado o lo carga **una sola vez**.

        Doble comprobación: la primera sin cerrojo de clave (camino rápido) y
        la segunda ya dentro del cerrojo, para que el hilo que esperó no
        vuelva a cargar lo que otro acaba de dejar en la caché.
        """
        now = self._clock()
        hit = self._lookup(key, now)
        if hit is not None:
            with self._global_lock:
                self._stats["hits"] += 1
            return hit.value

        with self._global_lock:
            self._stats["misses"] += 1
            key_lock = self._key_locks.setdefault(key, threading.Lock())

        with key_lock:
            # Segunda comprobación: otro hilo pudo cargar mientras esperábamos.
            now = self._clock()
            hit = self._lookup(key, now)
            if hit is not None:
                return hit.value
            value = loader()
            with self._global_lock:
                self._stats["loads"] += 1
                self._evict_if_needed()
                self._entries[key] = _Entry(value=value, expires_at=now + self._ttl)
            return value

    def invalidate(self, key: str) -> bool:
        """Elimina una entrada. Se usa tras el crypto-shredding de un tenant."""
        with self._global_lock:
            existed = self._entries.pop(key, None) is not None
            self._key_locks.pop(key, None)
            return existed

    def invalidate_prefix(self, prefix: str) -> int:
        """Elimina todas las entradas de un prefijo (por ejemplo, un tenant)."""
        with self._global_lock:
            targets = [k for k in self._entries if k.startswith(prefix)]
            for key in targets:
                self._entries.pop(key, None)
                self._key_locks.pop(key, None)
            return len(targets)

    def stats(self) -> Mapping[str, int]:
        with self._global_lock:
            return dict(self._stats)

    # -- Auxiliares --------------------------------------------------------

    def __len__(self) -> int:
        with self._global_lock:
            return len(self._entries)

    def __contains__(self, key: str) -> bool:
        return self._lookup(key, self._clock()) is not None

    def keys(self) -> Iterator[str]:
        with self._global_lock:
            return iter(tuple(self._entries.keys()))

    def clear(self) -> None:
        with self._global_lock:
            self._entries.clear()
            self._key_locks.clear()

    def _lookup(self, key: str, now: float) -> _Entry[T] | None:
        with self._global_lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if entry.is_expired(now):
                self._entries.pop(key, None)
                self._stats["expirations"] += 1
                return None
            return entry

    def _evict_if_needed(self) -> None:
        """Desalojo por la entrada más próxima a expirar (se llama con el cerrojo global)."""
        while len(self._entries) >= self._max_entries:
            oldest = min(self._entries.items(), key=lambda item: item[1].expires_at)[0]
            self._entries.pop(oldest, None)
            self._key_locks.pop(oldest, None)
            self._stats["evictions"] += 1


def tenant_cache_key(tenant_id: str, purpose: str) -> str:
    """Clave canónica de caché. El tenant va delante para poder invalidar por prefijo."""
    return f"{tenant_id}:{purpose}"


class CachedKeyProvider:
    """Envoltorio que cachea las claves deterministas de un `KeyProvider`.

    Solo se cachea lo determinista (`derive_key`): una clave de datos aleatoria
    por operación **no debe cachearse**, porque reutilizarla con el mismo nonce
    rompería la seguridad del cifrado.
    """

    __slots__ = ("_inner", "_cache")

    def __init__(self, inner: Any, cache: AtomicMaterialCache[bytes] | None = None) -> None:
        self._inner = inner
        self._cache: AtomicMaterialCache[bytes] = cache or AtomicMaterialCache()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def derive_key(self, tenant_id: Any, *, purpose: str, length: int = 32) -> bytes:
        key = tenant_cache_key(str(tenant_id), f"{purpose}:{length}")
        return self._cache.get_or_load(key, lambda: self._inner.derive_key(tenant_id, purpose=purpose, length=length))

    def shred_tenant_key(self, tenant_id: Any) -> bool:
        """Destruye la clave e **invalida la caché** del tenant en el mismo acto.

        Sin la invalidación, el material seguiría vivo en memoria hasta el TTL
        y el borrado no sería efectivo de inmediato.
        """
        self._cache.invalidate_prefix(f"{tenant_id}:")
        result: bool = self._inner.shred_tenant_key(tenant_id)
        return result

    @property
    def cache(self) -> AtomicMaterialCache[bytes]:
        return self._cache


__all__ = ["AtomicMaterialCache", "CachedKeyProvider", "tenant_cache_key"]
