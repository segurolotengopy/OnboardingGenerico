"""Puertos criptográficos.

La capa criptográfica **es la red de seguridad del multi-tenancy**, no una
defensa en profundidad opcional. GCP no puede aplicar aislamiento en el plano
de datos (no existe equivalente de `dynamodb:LeadingKeys`, y las Security
Rules de Firestore las ignoran las bibliotecas de servidor), de modo que el
cifrado de sobre por tenant con `tenant_id` como Associated Data es lo que
convierte un error de alcance en un **fallo de descifrado** en vez de una
fuga de datos.
"""

from __future__ import annotations

import abc
from typing import Any, Mapping, Sequence

from ..domain.value_objects import TenantId


class KeyProvider(abc.ABC):
    """Proveedor de material de clave por tenant.

    En AWS lo implementa el *hierarchical keyring* con su tabla de branch
    keys; en GCP, Cloud KMS con Tink. En ambos casos el material derivado se
    cachea en proceso (ver `crypto.material_cache`), porque una llamada a KMS
    por operación hace inviable la latencia del sistema.
    """

    @abc.abstractmethod
    def data_key_for(self, tenant_id: TenantId, *, purpose: str = "field") -> tuple[bytes, bytes]:
        """Devuelve `(clave_en_claro, clave_cifrada)` para el tenant.

        La clave cifrada se guarda junto al registro; la clave en claro nunca
        se persiste y solo vive en memoria durante la operación.
        """

    @abc.abstractmethod
    def unwrap(self, tenant_id: TenantId, wrapped_key: bytes, *, purpose: str = "field") -> bytes:
        """Descifra una clave envuelta. Lanza `DecryptionError` si el tenant no cuadra."""

    @abc.abstractmethod
    def derive_key(self, tenant_id: TenantId, *, purpose: str, length: int = 32) -> bytes:
        """Clave **determinista** derivada del material del tenant.

        Necesaria para dos usos que no admiten una clave aleatoria por
        operación: la firma del registro y los beacons de búsqueda. Ambos
        exigen que dos procesos distintos, en momentos distintos, obtengan el
        mismo valor para el mismo tenant.
        """

    @abc.abstractmethod
    def rotate(self, tenant_id: TenantId) -> str:
        """Genera una versión nueva de la clave raíz del tenant y la devuelve."""

    @abc.abstractmethod
    def shred_tenant_key(self, tenant_id: TenantId) -> bool:
        """Destruye el material del tenant (crypto-shredding).

        Tras esto, todo dato cifrado con esa clave es irrecuperable: es el
        mecanismo que sostiene el borrado del art. 17 del GDPR cuando el
        borrado físico no es viable.

        Nota operativa: Cloud KMS **no permite destrucción inmediata**; el
        valor por defecto es de 30 días y es configurable. El mínimo
        configurable no está documentado y debe verificarse antes de
        comprometer un SLA de borrado.
        """

    @abc.abstractmethod
    def is_shredded(self, tenant_id: TenantId) -> bool:
        """`True` si la clave del tenant fue destruida."""


class FieldCipher(abc.ABC):
    """Cifrado a nivel de atributo con política por campo.

    Existen tres directivas por atributo (`ENCRYPT_AND_SIGN`, `SIGN_ONLY`,
    `DO_NOTHING`). Las claves de partición y ordenación deben ser `SIGN_ONLY`
    —viajan en claro—, y por eso **nunca pueden contener PII**.
    """

    @abc.abstractmethod
    def encrypt_item(self, tenant_id: TenantId, item: Mapping[str, Any]) -> dict[str, Any]:
        """Cifra y firma un registro completo usando `tenant_id` como AAD."""

    @abc.abstractmethod
    def decrypt_item(self, tenant_id: TenantId, item: Mapping[str, Any]) -> dict[str, Any]:
        """Descifra y verifica.

        Lanza `DecryptionError` si el `tenant_id` no es el que se usó al
        cifrar. **Esta es la prueba de aislamiento**: un error de alcance
        produce un fallo, no una lectura cruzada.
        """

    @abc.abstractmethod
    def beacon(self, tenant_id: TenantId, field_name: str, value: str) -> str:
        """Índice determinista para consultas de igualdad sobre campo cifrado.

        Reimplementa los *searchable encryption beacons* del AWS Database
        Encryption SDK, que **no tienen equivalente en Tink**. El beacon es un
        HMAC con clave del tenant; el tenant va como primera parte, de modo
        que el índice sigue siendo tenant-scoped. Asumir el análisis de fuga
        de frecuencia es responsabilidad del diseño del campo indexado.
        """


class SecureRandom(abc.ABC):
    """Fuente de aleatoriedad criptográfica, inyectable para pruebas deterministas."""

    @abc.abstractmethod
    def token_bytes(self, length: int) -> bytes:
        """Bytes aleatorios de calidad criptográfica."""

    @abc.abstractmethod
    def token_hex(self, length: int) -> str:
        """Cadena hexadecimal aleatoria de `length` bytes."""


class MaterialCache(abc.ABC):
    """Caché de material criptográfico con carga atómica por clave.

    **No se usa `CachingCryptoMaterialsManager`.** El artículo de AWS que
    documenta el 77 % de ahorro (caso NICE Actimize) describe al CCMM como
    *la causa* del problema de *cache stampede* en entornos multihilo, no como
    su solución. La recomendación correcta es el *hierarchical keyring* o una
    caché con carga atómica por clave, que es lo que este puerto define.
    """

    @abc.abstractmethod
    def get_or_load(self, key: str, loader: Any) -> Any:
        """Devuelve el valor cacheado o lo carga **una sola vez** por clave."""

    @abc.abstractmethod
    def invalidate(self, key: str) -> bool:
        """Elimina una entrada. `True` si existía."""

    @abc.abstractmethod
    def invalidate_prefix(self, prefix: str) -> int:
        """Elimina todas las entradas con ese prefijo; devuelve cuántas."""

    @abc.abstractmethod
    def stats(self) -> Mapping[str, int]:
        """Aciertos, fallos y cargas efectivas. `loads <= misses` siempre."""


def assert_no_pii_in_keys(keys: Sequence[str], pii_fields: Sequence[str]) -> None:
    """Verificación de diseño: ninguna clave de índice puede llevar PII.

    Se ejecuta en las pruebas de arquitectura. `SIGN_ONLY` sobre la clave de
    partición significa que viaja en claro; si además lleva el número de
    documento, el cifrado no protege nada.
    """
    from ..errors import ValidationError  # import local: evita ciclo en el arranque

    offending = sorted(set(keys) & set(pii_fields))
    if offending:
        raise ValidationError(
            "hay campos PII usados como clave de índice; deben ser SIGN_ONLY sin PII",
            field="index_keys",
            offending=offending,
        )


__all__ = [
    "FieldCipher",
    "KeyProvider",
    "MaterialCache",
    "SecureRandom",
    "assert_no_pii_in_keys",
]
