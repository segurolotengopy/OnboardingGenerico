"""Cifrado de sobre con `tenant_id` como Associated Data.

**Por qué esto es un requisito y no una defensa opcional.** GCP no puede
aplicar aislamiento multi-tenant en el plano de datos: no existe equivalente
de `dynamodb:LeadingKeys`, IAM Conditions no expone atributos de clave de fila
y las Security Rules de Firestore son irrelevantes para un backend porque las
bibliotecas de servidor las ignoran por completo. Esa brecha es peligrosa
porque es **silenciosa**: el código funciona, simplemente no está aislado.

La mitigación que convierte un bug de alcance en un fallo seguro es
criptográfica. Con `tenant_id` en el AAD, leer un registro con el tenant
equivocado produce `DecryptionError`, no una fuga.

**Sobre esta implementación.** Es una implementación de referencia construida
solo con la biblioteca estándar (`hmac`, `hashlib`, `secrets`): AES-SIV en
modo *encrypt-then-MAC* no está en stdlib, así que se usa un cifrado de flujo
derivado por HKDF-SHA256 más un HMAC-SHA256 sobre `(nonce || AAD || cifrado)`.
Es correcta y suficiente para pruebas y desarrollo local, y **no sustituye** a
AWS Database Encryption SDK ni a Tink en producción: la clase
`EnvelopeCipher` es el punto de extensión, y los adaptadores de nube la
reemplazan conservando el mismo contrato de AAD.

Diferencias reales que conviene tener presentes al portar (brecha 4):

- Tink cubre el cifrado de sobre y el AAD, pero **no** la firma del registro
  completo, ni los atributos firmados-pero-no-cifrados, ni los *searchable
  encryption beacons*. Los beacons se reimplementan aquí como HMAC
  determinista con clave por tenant (`beacon`), asumiendo el análisis de fuga
  de frecuencia.
- Tink **no trae caché de material criptográfico**; sin ella, la latencia de
  KMS por operación hace inviable el sistema. Ver `material_cache.py`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from ..domain.value_objects import TenantId
from ..errors import DecryptionError, KeyDestroyedError
from ..ports.crypto import FieldCipher, KeyProvider, SecureRandom
from .field_policy import CryptoAction, FieldPolicy, default_policy

#: Etiqueta de versión del formato de sobre. Va autenticada dentro del AAD.
ENVELOPE_VERSION: str = "og-env-v1"

#: Longitud de la clave de datos y del nonce, en bytes.
DATA_KEY_BYTES: int = 32
NONCE_BYTES: int = 16


class SystemRandom(SecureRandom):
    """Aleatoriedad del sistema vía `secrets`."""

    def token_bytes(self, length: int) -> bytes:
        return secrets.token_bytes(length)

    def token_hex(self, length: int) -> str:
        return secrets.token_hex(length)


class DeterministicRandom(SecureRandom):
    """Aleatoriedad reproducible **solo para pruebas**.

    Deriva bytes de un contador con HKDF. Nunca debe usarse en producción; el
    contenedor solo la inyecta cuando el proveedor de nube es ``inmemory`` y
    la prueba lo pide explícitamente.
    """

    __slots__ = ("_seed", "_counter")

    def __init__(self, seed: bytes = b"og-test-seed") -> None:
        self._seed = seed
        self._counter = 0

    def token_bytes(self, length: int) -> bytes:
        self._counter += 1
        return _hkdf(self._seed, info=f"det:{self._counter}".encode("utf-8"), length=length)

    def token_hex(self, length: int) -> str:
        return self.token_bytes(length).hex()


def _hkdf(key_material: bytes, *, info: bytes, length: int, salt: bytes = b"") -> bytes:
    """HKDF-SHA256 (RFC 5869) implementado sobre `hmac` de la stdlib."""
    prk = hmac.new(salt or b"\x00" * 32, key_material, hashlib.sha256).digest()
    output = b""
    block = b""
    counter = 1
    while len(output) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        output += block
        counter += 1
    return output[:length]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    """Flujo pseudoaleatorio derivado de (clave, nonce) en modo contador."""
    output = b""
    counter = 0
    while len(output) < length:
        output += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return output[:length]


def _xor(data: bytes, stream: bytes) -> bytes:
    return bytes(a ^ b for a, b in zip(data, stream))


def build_aad(tenant_id: TenantId, *, context: Mapping[str, str] | None = None) -> bytes:
    """Construye el Associated Data canónico.

    El AAD **siempre** empieza por el tenant. `context` añade campos extra
    (por ejemplo `field` o `session_id`) que quedan autenticados pero no
    cifrados: cambiarlos invalida el descifrado.
    """
    parts = [ENVELOPE_VERSION, f"tenant={tenant_id.value}"]
    for key in sorted((context or {}).keys()):
        parts.append(f"{key}={context[key]}")  # type: ignore[index]
    return "|".join(parts).encode("utf-8")


@dataclass(frozen=True, slots=True)
class Envelope:
    """Sobre cifrado serializable."""

    version: str
    wrapped_key: str
    nonce: str
    ciphertext: str
    tag: str

    def as_dict(self) -> dict[str, str]:
        return {
            "version": self.version,
            "wrapped_key": self.wrapped_key,
            "nonce": self.nonce,
            "ciphertext": self.ciphertext,
            "tag": self.tag,
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> Envelope:
        try:
            return cls(
                version=str(data["version"]),
                wrapped_key=str(data["wrapped_key"]),
                nonce=str(data["nonce"]),
                ciphertext=str(data["ciphertext"]),
                tag=str(data["tag"]),
            )
        except KeyError as exc:
            raise DecryptionError("sobre mal formado: falta un campo", missing=str(exc)) from exc


class LocalKeyProvider(KeyProvider):
    """Proveedor de claves de referencia, con una raíz por proceso.

    Sustituye a KMS en desarrollo y pruebas. La clave de tenant se **deriva**
    de la raíz con HKDF usando el `tenant_id` como `info`, de modo que dos
    tenants nunca comparten material aunque compartan raíz.
    """

    __slots__ = ("_root", "_random", "_shredded", "_versions")

    def __init__(self, root_key: bytes | None = None, *, random_source: SecureRandom | None = None) -> None:
        self._root = root_key or secrets.token_bytes(DATA_KEY_BYTES)
        self._random = random_source or SystemRandom()
        self._shredded: set[str] = set()
        self._versions: dict[str, int] = {}

    def _tenant_key(self, tenant_id: TenantId, purpose: str) -> bytes:
        if tenant_id.value in self._shredded:
            raise KeyDestroyedError(
                "el material de clave del tenant fue destruido", tenant_id=tenant_id.value
            )
        version = self._versions.get(tenant_id.value, 1)
        info = f"tenant={tenant_id.value}|purpose={purpose}|v={version}".encode("utf-8")
        return _hkdf(self._root, info=info, length=DATA_KEY_BYTES)

    def data_key_for(self, tenant_id: TenantId, *, purpose: str = "field") -> tuple[bytes, bytes]:
        plaintext_key = self._random.token_bytes(DATA_KEY_BYTES)
        kek = self._tenant_key(tenant_id, purpose)
        nonce = self._random.token_bytes(NONCE_BYTES)
        wrapped = nonce + _xor(plaintext_key, _keystream(kek, nonce, DATA_KEY_BYTES))
        mac = hmac.new(kek, wrapped + tenant_id.aad, hashlib.sha256).digest()
        return plaintext_key, wrapped + mac

    def unwrap(self, tenant_id: TenantId, wrapped_key: bytes, *, purpose: str = "field") -> bytes:
        kek = self._tenant_key(tenant_id, purpose)
        if len(wrapped_key) != NONCE_BYTES + DATA_KEY_BYTES + 32:
            raise DecryptionError("clave envuelta con longitud inválida")
        body, mac = wrapped_key[:-32], wrapped_key[-32:]
        expected = hmac.new(kek, body + tenant_id.aad, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            # Ocurre cuando el tenant no es el que envolvió la clave.
            raise DecryptionError("no se pudo desenvolver la clave para este tenant")
        nonce, wrapped = body[:NONCE_BYTES], body[NONCE_BYTES:]
        return _xor(wrapped, _keystream(kek, nonce, DATA_KEY_BYTES))

    def derive_key(self, tenant_id: TenantId, *, purpose: str, length: int = 32) -> bytes:
        return _hkdf(self._tenant_key(tenant_id, purpose), info=b"derive:" + purpose.encode(), length=length)

    def rotate(self, tenant_id: TenantId) -> str:
        version = self._versions.get(tenant_id.value, 1) + 1
        self._versions[tenant_id.value] = version
        return f"v{version}"

    def shred_tenant_key(self, tenant_id: TenantId) -> bool:
        if tenant_id.value in self._shredded:
            return False
        self._shredded.add(tenant_id.value)
        return True

    def is_shredded(self, tenant_id: TenantId) -> bool:
        return tenant_id.value in self._shredded


class EnvelopeCipher:
    """Cifrado de sobre autenticado con AAD.

    Punto de extensión: los adaptadores de nube (`dbesdk_cipher`,
    `tink_cipher`) sustituyen esta clase conservando la firma y, sobre todo,
    la semántica del AAD.
    """

    __slots__ = ("_keys", "_random")

    def __init__(self, key_provider: KeyProvider, *, random_source: SecureRandom | None = None) -> None:
        self._keys = key_provider
        self._random = random_source or SystemRandom()

    def encrypt(
        self,
        tenant_id: TenantId,
        plaintext: bytes,
        *,
        context: Mapping[str, str] | None = None,
    ) -> Envelope:
        """Cifra y autentica `plaintext` bajo el AAD del tenant."""
        data_key, wrapped = self._keys.data_key_for(tenant_id)
        nonce = self._random.token_bytes(NONCE_BYTES)
        aad = build_aad(tenant_id, context=context)
        enc_key = _hkdf(data_key, info=b"enc" + aad, length=DATA_KEY_BYTES)
        mac_key = _hkdf(data_key, info=b"mac" + aad, length=DATA_KEY_BYTES)
        ciphertext = _xor(plaintext, _keystream(enc_key, nonce, len(plaintext)))
        tag = hmac.new(mac_key, nonce + aad + ciphertext, hashlib.sha256).digest()
        return Envelope(
            version=ENVELOPE_VERSION,
            wrapped_key=_b64(wrapped),
            nonce=_b64(nonce),
            ciphertext=_b64(ciphertext),
            tag=_b64(tag),
        )

    def decrypt(
        self,
        tenant_id: TenantId,
        envelope: Envelope | Mapping[str, Any],
        *,
        context: Mapping[str, str] | None = None,
    ) -> bytes:
        """Descifra y verifica.

        Lanza `DecryptionError` si el tenant o el contexto no son los del
        cifrado. Es el comportamiento buscado: un error de alcance falla.
        """
        env = envelope if isinstance(envelope, Envelope) else Envelope.from_mapping(envelope)
        if env.version != ENVELOPE_VERSION:
            raise DecryptionError("versión de sobre no soportada", version=env.version)
        wrapped = _unb64(env.wrapped_key)
        data_key = self._keys.unwrap(tenant_id, wrapped)
        aad = build_aad(tenant_id, context=context)
        enc_key = _hkdf(data_key, info=b"enc" + aad, length=DATA_KEY_BYTES)
        mac_key = _hkdf(data_key, info=b"mac" + aad, length=DATA_KEY_BYTES)
        nonce = _unb64(env.nonce)
        ciphertext = _unb64(env.ciphertext)
        expected_tag = hmac.new(mac_key, nonce + aad + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(env.tag), expected_tag):
            raise DecryptionError("fallo de autenticación del sobre: AAD o clave incorrectos")
        return _xor(ciphertext, _keystream(enc_key, nonce, len(ciphertext)))


class EnvelopeFieldCipher(FieldCipher):
    """Aplica la política por atributo sobre un registro completo.

    - `ENCRYPT_AND_SIGN`: el valor se sustituye por un sobre.
    - `SIGN_ONLY`: el valor viaja en claro pero entra en la firma del registro.
    - `DO_NOTHING`: ni se cifra ni se firma (metadatos volátiles).

    La firma del registro es lo que el AWS Database Encryption SDK aporta y
    Tink no: sin ella, un atacante con escritura podría alterar un atributo
    `SIGN_ONLY` sin que nada lo detecte.
    """

    __slots__ = ("_cipher", "_policy", "_keys")

    SIGNATURE_FIELD = "__og_signature"
    ENVELOPE_PREFIX = "__og_env__"

    def __init__(
        self,
        cipher: EnvelopeCipher,
        key_provider: KeyProvider,
        policy: FieldPolicy | None = None,
    ) -> None:
        self._cipher = cipher
        self._keys = key_provider
        self._policy = policy or default_policy()

    def encrypt_item(self, tenant_id: TenantId, item: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name, value in item.items():
            action = self._policy.action_for(name)
            if action is CryptoAction.ENCRYPT_AND_SIGN and value is not None:
                envelope = self._cipher.encrypt(
                    tenant_id, _to_bytes(value), context={"field": name}
                )
                result[self.ENVELOPE_PREFIX + name] = envelope.as_dict()
            else:
                result[name] = value
        result[self.SIGNATURE_FIELD] = self._sign(tenant_id, result)
        return result

    def decrypt_item(self, tenant_id: TenantId, item: Mapping[str, Any]) -> dict[str, Any]:
        stored_signature = item.get(self.SIGNATURE_FIELD)
        body = {k: v for k, v in item.items() if k != self.SIGNATURE_FIELD}
        if stored_signature is not None:
            expected = self._sign(tenant_id, body)
            if not hmac.compare_digest(str(stored_signature), expected):
                raise DecryptionError("la firma del registro no verifica para este tenant")

        result: dict[str, Any] = {}
        for name, value in body.items():
            if name.startswith(self.ENVELOPE_PREFIX):
                field_name = name[len(self.ENVELOPE_PREFIX) :]
                plaintext = self._cipher.decrypt(tenant_id, value, context={"field": field_name})
                result[field_name] = _from_bytes(plaintext)
            else:
                result[name] = value
        return result

    def beacon(self, tenant_id: TenantId, field_name: str, value: str) -> str:
        """HMAC determinista con clave del tenant, truncado a 128 bits.

        El truncado limita el tamaño del índice y no debilita la resistencia a
        preimagen para este uso. El tenant es la primera parte del material de
        clave, así que el índice sigue siendo tenant-scoped.
        """
        key = self._beacon_key(tenant_id)
        digest = hmac.new(key, f"{field_name}={value}".encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{tenant_id.value}#{digest[:32]}"

    def _beacon_key(self, tenant_id: TenantId) -> bytes:
        # El material de beacon debe ser **estable entre procesos**: se deriva
        # de forma determinista del material del tenant, nunca de una clave de
        # datos aleatoria por operación.
        return self._keys.derive_key(tenant_id, purpose="beacon")

    def _sign(self, tenant_id: TenantId, body: Mapping[str, Any]) -> str:
        signing_key = self._keys.derive_key(tenant_id, purpose="sign")
        payload = _canonical(body).encode("utf-8")
        return hmac.new(signing_key, tenant_id.aad + payload, hashlib.sha256).hexdigest()


def _canonical(body: Mapping[str, Any]) -> str:
    import json

    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _to_bytes(value: Any) -> bytes:
    import json

    if isinstance(value, bytes):
        return b"b:" + value
    if isinstance(value, str):
        return b"s:" + value.encode("utf-8")
    return b"j:" + json.dumps(value, sort_keys=True, default=str).encode("utf-8")


def _from_bytes(data: bytes) -> Any:
    import json

    prefix, payload = data[:2], data[2:]
    if prefix == b"b:":
        return payload
    if prefix == b"s:":
        return payload.decode("utf-8")
    return json.loads(payload.decode("utf-8"))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(data: str) -> bytes:
    try:
        return base64.b64decode(data.encode("ascii"), validate=True)
    except Exception as exc:  # noqa: BLE001 - cualquier fallo aquí es dato corrupto
        raise DecryptionError("campo base64 inválido en el sobre") from exc


def shred_tenant_key(key_provider: KeyProvider, tenant_id: TenantId) -> bool:
    """Atajo de dominio para el crypto-shredding de un tenant.

    Tras esto, todo dato cifrado con ese material es irrecuperable. Es el
    mecanismo que sostiene el borrado cuando el borrado físico no es viable
    (copias de seguridad, réplicas, almacenamiento inmutable).
    """
    return key_provider.shred_tenant_key(tenant_id)


KeyLoader = Callable[[], bytes]

__all__ = [
    "DATA_KEY_BYTES",
    "ENVELOPE_VERSION",
    "DeterministicRandom",
    "Envelope",
    "EnvelopeCipher",
    "EnvelopeFieldCipher",
    "LocalKeyProvider",
    "SystemRandom",
    "build_aad",
    "shred_tenant_key",
]
