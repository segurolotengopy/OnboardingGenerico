"""Almacén de objetos en memoria.

Reproduce el comportamiento relevante de S3 y GCS:

- La clave se prefija con el tenant, de modo que un llamador **no puede**
  escribir ni leer en el espacio de otro tenant aunque construya la clave a
  mano: el prefijo se antepone en el adaptador, no lo aporta el llamador.
- `get` verifica el sha256 declarado antes de devolver los bytes
  (invariante I6): sustituir el objeto tras el registro produce
  `IntegrityError`.
- Las URLs prefirmadas son opacas y caducan; aquí se emulan con un token
  firmado en memoria, suficiente para probar el flujo de carga directa.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ...domain.value_objects import ObjectRef, TenantId
from ...errors import IntegrityError, ObjectNotFoundError, TenantIsolationError
from ...ports.object_storage import ObjectStorage

SCHEME: str = "mem"


@dataclass(slots=True)
class _StoredObject:
    data: bytes
    content_type: str
    metadata: dict[str, str]
    sha256: str


class InMemoryObjectStorage(ObjectStorage):
    """Almacén de objetos con prefijo obligatorio por tenant."""

    __slots__ = ("bucket", "_objects", "_presigned", "_lock", "_clock")

    def __init__(self, bucket: str = "og-dev-artifacts", clock: Any = None) -> None:
        self.bucket = bucket
        self._objects: dict[str, _StoredObject] = {}
        self._presigned: dict[str, tuple[str, float, str]] = {}
        self._lock = threading.RLock()
        self._clock = clock or time.monotonic

    # -- Auxiliares -------------------------------------------------------

    @staticmethod
    def _scoped_key(tenant_id: TenantId, key: str) -> str:
        """Prefija con el tenant y rechaza escapes de ruta."""
        cleaned = key.lstrip("/")
        if ".." in cleaned.split("/"):
            raise TenantIsolationError(
                "la clave contiene un salto de directorio", tenant_id=tenant_id.value
            )
        prefix = f"tenants/{tenant_id.value}/"
        if cleaned.startswith(prefix):
            return cleaned
        return prefix + cleaned

    def _assert_in_scope(self, tenant_id: TenantId, ref: ObjectRef) -> str:
        prefix = f"tenants/{tenant_id.value}/"
        if not ref.key.startswith(prefix):
            # Es la detección temprana; el cifrado con AAD es la red de abajo.
            raise TenantIsolationError(
                "la referencia apunta fuera del alcance del tenant",
                tenant_id=tenant_id.value,
            )
        if ref.bucket != self.bucket:
            raise TenantIsolationError(
                "la referencia apunta a otro bucket", tenant_id=tenant_id.value, bucket=ref.bucket
            )
        return ref.key

    # -- API del puerto ---------------------------------------------------

    def put(
        self,
        tenant_id: TenantId,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectRef:
        scoped = self._scoped_key(tenant_id, key)
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            self._objects[scoped] = _StoredObject(
                data=bytes(data),
                content_type=content_type,
                metadata=dict(metadata or {}),
                sha256=digest,
            )
        return ObjectRef.build(
            scheme=SCHEME,
            bucket=self.bucket,
            key=scoped,
            sha256=digest,
            size_bytes=len(data),
            content_type=content_type,
        )

    def get(self, tenant_id: TenantId, ref: ObjectRef) -> bytes:
        scoped = self._assert_in_scope(tenant_id, ref)
        with self._lock:
            stored = self._objects.get(scoped)
        if stored is None:
            raise ObjectNotFoundError("el objeto no existe", key=scoped)
        if stored.sha256 != ref.sha256:
            raise IntegrityError(
                "el sha256 del objeto no coincide con el declarado (invariante I6)",
                key=scoped,
                expected=ref.sha256,
                actual=stored.sha256,
            )
        return stored.data

    def exists(self, tenant_id: TenantId, ref: ObjectRef) -> bool:
        try:
            scoped = self._assert_in_scope(tenant_id, ref)
        except TenantIsolationError:
            return False
        with self._lock:
            return scoped in self._objects

    def presign_put(
        self,
        tenant_id: TenantId,
        key: str,
        *,
        ttl_seconds: int = 900,
        content_type: str = "application/octet-stream",
        max_bytes: int | None = None,
    ) -> str:
        scoped = self._scoped_key(tenant_id, key)
        token = hashlib.sha256(
            f"put:{scoped}:{self._clock()}:{ttl_seconds}".encode("utf-8")
        ).hexdigest()[:32]
        with self._lock:
            self._presigned[token] = (scoped, self._clock() + ttl_seconds, "PUT")
        limit = f"&max_bytes={max_bytes}" if max_bytes else ""
        return f"{SCHEME}://{self.bucket}/{scoped}?token={token}&op=put&ct={content_type}{limit}"

    def presign_get(self, tenant_id: TenantId, ref: ObjectRef, *, ttl_seconds: int = 900) -> str:
        scoped = self._assert_in_scope(tenant_id, ref)
        token = hashlib.sha256(
            f"get:{scoped}:{self._clock()}:{ttl_seconds}".encode("utf-8")
        ).hexdigest()[:32]
        with self._lock:
            self._presigned[token] = (scoped, self._clock() + ttl_seconds, "GET")
        return f"{SCHEME}://{self.bucket}/{scoped}?token={token}&op=get"

    def delete_many(self, tenant_id: TenantId, refs: Sequence[ObjectRef]) -> int:
        deleted = 0
        for ref in refs:
            try:
                scoped = self._assert_in_scope(tenant_id, ref)
            except TenantIsolationError:
                continue
            with self._lock:
                if self._objects.pop(scoped, None) is not None:
                    deleted += 1
        return deleted

    def delete_prefix(self, tenant_id: TenantId, prefix: str) -> int:
        scoped_prefix = self._scoped_key(tenant_id, prefix)
        with self._lock:
            targets = [k for k in self._objects if k.startswith(scoped_prefix)]
            for key in targets:
                self._objects.pop(key, None)
        return len(targets)

    # -- Utilidades de prueba ---------------------------------------------

    def resolve_presigned(self, url: str) -> str | None:
        """Valida una URL prefirmada emulada y devuelve la clave, o `None`."""
        if "token=" not in url:
            return None
        token = url.split("token=", 1)[1].split("&", 1)[0]
        with self._lock:
            entry = self._presigned.get(token)
        if entry is None or entry[1] <= self._clock():
            return None
        return entry[0]

    def object_count(self, tenant_id: TenantId | None = None) -> int:
        with self._lock:
            if tenant_id is None:
                return len(self._objects)
            prefix = f"tenants/{tenant_id.value}/"
            return sum(1 for k in self._objects if k.startswith(prefix))


__all__ = ["InMemoryObjectStorage"]
