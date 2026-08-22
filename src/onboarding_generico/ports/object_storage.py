"""Puerto de almacenamiento de objetos.

Se porta sin fricción entre S3 y GCS, así que la interfaz se define
libremente. La única restricción de diseño la impone el orquestador: **ningún
binario viaja por el estado**, siempre `ObjectRef`. Cloud Workflows tiene un
tope de 512 KB acumulados por ejecución (el límite dominante) y Step Functions
256 KiB por payload.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence

from ..domain.value_objects import ObjectRef, TenantId


class ObjectStorage(abc.ABC):
    """Almacén de objetos con URLs prefirmadas y borrado masivo."""

    @abc.abstractmethod
    def put(
        self,
        tenant_id: TenantId,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectRef:
        """Sube un objeto y devuelve su referencia con el sha256 calculado.

        La clave se prefija con el tenant en el adaptador: el llamador pasa
        una clave relativa y nunca puede escribir en el espacio de otro tenant.
        """

    @abc.abstractmethod
    def get(self, tenant_id: TenantId, ref: ObjectRef) -> bytes:
        """Descarga el objeto y verifica el sha256 declarado (invariante I6).

        Lanza `IntegrityError` si el contenido no coincide, y
        `ObjectNotFoundError` si no existe.
        """

    @abc.abstractmethod
    def exists(self, tenant_id: TenantId, ref: ObjectRef) -> bool:
        """`True` si el objeto existe dentro del alcance del tenant."""

    @abc.abstractmethod
    def presign_put(
        self,
        tenant_id: TenantId,
        key: str,
        *,
        ttl_seconds: int = 900,
        content_type: str = "application/octet-stream",
        max_bytes: int | None = None,
    ) -> str:
        """URL prefirmada de carga directa desde el cliente.

        La carga directa evita que la imagen atraviese el middleware, lo que
        reduce coste y superficie de exposición de datos biométricos.
        """

    @abc.abstractmethod
    def presign_get(self, tenant_id: TenantId, ref: ObjectRef, *, ttl_seconds: int = 900) -> str:
        """URL prefirmada de lectura, para entregarla a un proveedor externo."""

    @abc.abstractmethod
    def delete_many(self, tenant_id: TenantId, refs: Sequence[ObjectRef]) -> int:
        """Borra en lote y devuelve cuántos objetos se eliminaron."""

    @abc.abstractmethod
    def delete_prefix(self, tenant_id: TenantId, prefix: str) -> int:
        """Borra todo bajo un prefijo. Base del borrado por sesión y por tenant."""


__all__ = ["ObjectStorage"]
