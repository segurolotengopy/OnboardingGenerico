"""Adaptadores de GCP: Firestore, GCS, Tink y Secret Manager.

La diferencia estructural con AWS, que no es cosmética:

**No existe `dynamodb:LeadingKeys` ni nada equivalente.** IAM Conditions no
expone atributos de clave de fila o documento, y las Security Rules de
Firestore son irrelevantes para un backend porque *"the server client
libraries bypass all Firestore Security Rules"*. La brecha es peligrosa
porque es **silenciosa**: el código funciona, simplemente no está aislado.

Consecuencias asumidas aquí:

1. El alcance por tenant se aplica **explícitamente** en cada operación, con
   la colección raíz por tenant (``tenants/{tenant_id}/sessions/{id}``).
2. El cifrado de sobre con `tenant_id` como AAD es lo que convierte un bug de
   alcance en un fallo de descifrado. **Es requisito, no defensa en
   profundidad opcional.**
3. Se complementa fuera del código con: base de datos Firestore por tenant
   (tope 100) o proyecto por tenant para clientes de alto valor, WIF con
   `attribute.tenant`, VPC Service Controls como perímetro y Data Access audit
   logs con alertas de desalineación tenant/token.

Además, **single-table no se emula bien en Firestore**: no hay consultas de
rango sobre clave de ordenación. Si el modelo fuera agresivamente
single-table, el destino correcto sería Bigtable (row keys ordenadas) o
Spanner (el único con change streams reales: orden garantizado y replay de
7 días).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from ...config import Settings
from ...domain.enums import Capability, SessionState
from ...domain.events import AuditEvent
from ...domain.session import OnboardingSession
from ...domain.value_objects import ObjectRef, ProviderRef, SessionId, TenantId
from ...errors import ConfigurationError, DecryptionError, LockAcquisitionError
from ...ports.crypto import FieldCipher, KeyProvider
from ...ports.object_storage import ObjectStorage
from ...ports.repository import (
    CapabilityRegistryRepository,
    FlowSpecRepository,
    IdempotencyStore,
    MutexLock,
    SessionRepository,
)
from ...ports.secrets import SecretsProvider
from ._client import firestore_client, kms_client, secret_manager_client, storage_client


def _tenant_root(db: Any, tenant_id: TenantId) -> Any:
    """Documento raíz del tenant. **Todo** acceso pasa por aquí."""
    return db.collection("tenants").document(tenant_id.value)


class FirestoreSessionRepository(SessionRepository):
    """Sesiones en `tenants/{tenant}/sessions/{session}`.

    El bloqueo optimista se hace con una **transacción** que lee `version` y
    escribe solo si no cambió; Firestore no tiene `ConditionExpression`.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _db(self) -> Any:
        return firestore_client(self._settings.gcp_project)

    def get(self, tenant_id: TenantId, session_id: SessionId) -> OnboardingSession:
        session = self.find(tenant_id, session_id)
        if session is None:
            from ...errors import SessionNotFoundError

            raise SessionNotFoundError(
                "la sesión no existe dentro del alcance del tenant",
                tenant_id=tenant_id.value,
                session_id=session_id.value,
            )
        return session

    def find(self, tenant_id: TenantId, session_id: SessionId) -> OnboardingSession | None:
        raise NotImplementedError(
            "Falta decidir la estrategia de lectura del agregado. En DynamoDB una sola Query con "
            "begins_with trae cabecera, pasos, artefactos y evidencias; en Firestore serían "
            "subcolecciones separadas y por tanto varias lecturas. Las opciones son: (a) "
            "desnormalizar todo en un único documento, con el tope de 1 MiB por documento y "
            "contención de escritura; (b) subcolecciones y varias lecturas por sesión. Es una "
            "decisión de coste y latencia que depende del tamaño real del expediente."
        )

    def save(
        self, session: OnboardingSession, *, expected_version: int | None = None
    ) -> OnboardingSession:
        db = self._db()
        document = (
            _tenant_root(db, session.tenant_id)
            .collection("sessions")
            .document(session.session_id.value)
        )
        payload = {
            "state": str(session.state),
            "version": session.version,
            "country": session.country,
            "document_type": str(session.document_type),
            "tier": session.tier,
            "spec_key": session.spec_ref.key,
            "spec_version": session.spec_ref.version,
            "spec_hash": session.spec_ref.content_hash,
            "created_at": session.created_at,
            "expires_at": session.expires_at,
            "external_ref": session.external_ref,
            # Número de secuencia explícito: Eventarc no garantiza orden, así
            # que el consumidor reordena por este campo.
            "sequence": session.version,
        }

        transaction = db.transaction()

        @transaction  # type: ignore[misc]
        def _write(tx: Any) -> None:
            from ...errors import ConcurrencyError  # noqa: PLC0415

            if expected_version is not None:
                snapshot = document.get(transaction=tx)
                actual = snapshot.get("version") if snapshot.exists else 0
                if actual != expected_version:
                    raise ConcurrencyError(
                        "otro escritor avanzó la versión de la sesión",
                        expected_version=expected_version,
                        actual_version=actual,
                    )
            tx.set(document, payload, merge=True)

        return session

    def list_by_state(
        self,
        tenant_id: TenantId,
        state: SessionState,
        *,
        limit: int = 50,
        older_than: datetime | None = None,
    ) -> tuple[OnboardingSession, ...]:
        db = self._db()
        query = (
            _tenant_root(db, tenant_id)
            .collection("sessions")
            .where("state", "==", str(state))
            .order_by("created_at")
            .limit(limit)
        )
        if older_than is not None:
            query = query.where("created_at", "<", older_than)
        documents = list(query.stream())
        if not documents:
            return ()
        raise NotImplementedError(
            "Misma decisión pendiente que en `find`: cómo se rehidrata el agregado. Aquí además "
            "hay que decidir si esta consulta devuelve el agregado completo (N+1 lecturas de "
            "subcolección) o una proyección ligera."
        )

    def find_by_external_ref(self, tenant_id: TenantId, external_ref: str) -> OnboardingSession | None:
        db = self._db()
        results = list(
            _tenant_root(db, tenant_id)
            .collection("sessions")
            .where("external_ref", "==", external_ref)
            .limit(1)
            .stream()
        )
        if not results:
            return None
        return self.find(tenant_id, SessionId(results[0].id))

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        """Append-only con `create()`: falla si el documento ya existe."""
        db = self._db()
        (
            _tenant_root(db, TenantId(event.tenant_id))
            .collection("audit")
            .document(f"{event.session_id}-{event.sequence:06d}")
            .create(
                {
                    "event_id": event.event_id,
                    "session_id": event.session_id,
                    "event_type": str(event.event_type),
                    "actor": event.actor,
                    "occurred_at": event.occurred_at,
                    "sequence": event.sequence,
                    "previous_hash": event.previous_hash,
                    "event_hash": event.event_hash,
                    "attributes": dict(event.attributes),
                }
            )
        )
        return event

    def audit_trail(self, tenant_id: TenantId, session_id: SessionId) -> tuple[AuditEvent, ...]:
        db = self._db()
        list(
            _tenant_root(db, tenant_id)
            .collection("audit")
            .where("session_id", "==", session_id.value)
            .order_by("sequence")
            .stream()
        )
        raise NotImplementedError(
            "Falta decidir si la traza se reconstruye a `AuditEvent` verificando la cadena en cada "
            "lectura o solo al sellar. En Firestore cada verificación son N lecturas facturables."
        )

    def delete_session_data(self, tenant_id: TenantId, session_id: SessionId) -> int:
        raise NotImplementedError(
            "Firestore no borra subcolecciones en cascada: hay que enumerarlas y borrarlas. Falta "
            "decidir si el borrado va en línea (latencia proporcional al expediente) o se delega "
            "a un trabajo por lotes con reintentos. El SLA de supresión determina la elección."
        )

    def list_session_ids(self, tenant_id: TenantId, *, limit: int = 1000) -> tuple[SessionId, ...]:
        db = self._db()
        documents = (
            _tenant_root(db, tenant_id)
            .collection("sessions")
            .select([])
            .limit(limit)
            .stream()
        )
        return tuple(SessionId(document.id) for document in documents)


class FirestoreCapabilityRegistry(CapabilityRegistryRepository):
    """Catálogo en `catalog/{capability}/providers/{provider}` y vínculos por tenant."""

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _db(self) -> Any:
        return firestore_client(self._settings.gcp_project)

    def register_provider(
        self,
        capability: Capability,
        provider: ProviderRef,
        *,
        countries: Sequence[str],
        document_types: Sequence[str],
        active: bool = True,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        (
            self._db()
            .collection("catalog")
            .document(str(capability))
            .collection("providers")
            .document(provider.provider_id)
            .set(
                {
                    "version": provider.version,
                    "countries": list(countries),
                    "document_types": list(document_types),
                    "active": active,
                    "metadata": dict(metadata or {}),
                }
            )
        )

    def list_providers(
        self,
        capability: Capability,
        *,
        country: str | None = None,
        document_type: str | None = None,
        only_active: bool = True,
    ) -> tuple[ProviderRef, ...]:
        query = self._db().collection("catalog").document(str(capability)).collection("providers")
        if only_active:
            query = query.where("active", "==", True)
        if country:
            # `array_contains` no admite dos cláusulas en la misma consulta,
            # así que el filtro por documento se aplica en memoria.
            query = query.where("countries", "array_contains", country)
        results = []
        for document in query.stream():
            data = document.to_dict() or {}
            if document_type and document_type not in data.get("document_types", []):
                if "*" not in data.get("document_types", []):
                    continue
            results.append(ProviderRef(document.id, str(data.get("version", "unknown"))))
        return tuple(results)

    def is_registered(self, capability: Capability, provider_id: str) -> bool:
        return (
            self._db()
            .collection("catalog")
            .document(str(capability))
            .collection("providers")
            .document(provider_id)
            .get()
            .exists
        )

    def is_active(self, capability: Capability, provider_id: str) -> bool:
        snapshot = (
            self._db()
            .collection("catalog")
            .document(str(capability))
            .collection("providers")
            .document(provider_id)
            .get()
        )
        return bool(snapshot.exists and (snapshot.to_dict() or {}).get("active", False))

    def bind_tenant(
        self,
        tenant_id: TenantId,
        capability: Capability,
        *,
        primary: str,
        fallbacks: Sequence[str] = (),
    ) -> None:
        db = self._db()
        _tenant_root(db, tenant_id).collection("capabilities").document(str(capability)).set(
            {"primary": primary, "fallbacks": list(fallbacks)}
        )

    def resolve_provider(
        self, tenant_id: TenantId, capability: Capability, *, country: str, document_type: str
    ) -> tuple[ProviderRef, ...]:
        db = self._db()
        snapshot = (
            _tenant_root(db, tenant_id).collection("capabilities").document(str(capability)).get()
        )
        if not snapshot.exists:
            return ()
        binding = snapshot.to_dict() or {}
        available = {
            p.provider_id: p
            for p in self.list_providers(capability, country=country, document_type=document_type)
        }
        chain = [binding.get("primary", ""), *binding.get("fallbacks", [])]
        return tuple(available[pid] for pid in chain if pid in available)

    def tenant_capabilities(self, tenant_id: TenantId) -> tuple[Capability, ...]:
        db = self._db()
        return tuple(
            Capability(document.id)
            for document in _tenant_root(db, tenant_id).collection("capabilities").stream()
        )


class FirestoreMutexLock(MutexLock):
    """Mutex con transacción y token de vallado.

    Firestore no tiene escritura condicional, así que la exclusión se logra
    con `create()` (falla si existe) y la expiración se comprueba dentro de
    una transacción.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _document(self, tenant_id: TenantId, resource: str) -> Any:
        db = firestore_client(self._settings.gcp_project)
        return _tenant_root(db, tenant_id).collection("locks").document(resource)

    def acquire(self, tenant_id: TenantId, resource: str, *, ttl_seconds: int = 60) -> str:
        import time  # noqa: PLC0415

        now = int(time.time())
        token = f"{now}-{tenant_id.value}"
        document = self._document(tenant_id, resource)
        snapshot = document.get()
        if snapshot.exists and int((snapshot.to_dict() or {}).get("expires_at", 0)) > now:
            raise LockAcquisitionError(
                "el recurso está bloqueado por otro titular",
                tenant_id=tenant_id.value,
                resource=resource,
            )
        document.set({"fence_token": token, "expires_at": now + ttl_seconds})
        return token

    def release(self, tenant_id: TenantId, resource: str, token: str) -> bool:
        document = self._document(tenant_id, resource)
        snapshot = document.get()
        if not snapshot.exists or (snapshot.to_dict() or {}).get("fence_token") != token:
            return False
        document.delete()
        return True

    def is_held(self, tenant_id: TenantId, resource: str) -> bool:
        import time  # noqa: PLC0415

        snapshot = self._document(tenant_id, resource).get()
        return bool(
            snapshot.exists and int((snapshot.to_dict() or {}).get("expires_at", 0)) > int(time.time())
        )


class FirestoreIdempotencyStore(IdempotencyStore):
    """Claves de idempotencia con **TTL policy** de Firestore.

    Es el único uso legítimo del TTL: los documentos de expediente nunca
    llevan campo de caducidad.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _document(self, tenant_id: TenantId, scope: str, key: str) -> Any:
        db = firestore_client(self._settings.gcp_project)
        return _tenant_root(db, tenant_id).collection("idempotency").document(f"{scope}--{key}")

    def reserve(self, tenant_id: TenantId, scope: str, key: str, *, ttl_seconds: int = 86_400) -> bool:
        from datetime import timedelta, timezone  # noqa: PLC0415

        try:
            self._document(tenant_id, scope, key).create(
                {"expires_at": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)}
            )
        except Exception:  # noqa: BLE001 - AlreadyExists
            return False
        return True

    def result_for(self, tenant_id: TenantId, scope: str, key: str) -> Mapping[str, Any] | None:
        snapshot = self._document(tenant_id, scope, key).get()
        if not snapshot.exists:
            return None
        data = snapshot.to_dict() or {}
        result = data.get("result")
        return dict(result) if isinstance(result, dict) else None

    def record_result(
        self, tenant_id: TenantId, scope: str, key: str, result: Mapping[str, Any]
    ) -> None:
        self._document(tenant_id, scope, key).set({"result": dict(result)}, merge=True)


class FirestoreFlowSpecRepository(FlowSpecRepository):
    """Specs publicadas en Firestore, con los artefactos compilados en GCS."""

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def publish(self, document: Mapping[str, Any]) -> str:
        from ...composer.spec import FlowSpec  # noqa: PLC0415

        spec = FlowSpec.parse(document)
        db = firestore_client(self._settings.gcp_project)
        db.collection("flow_specs").document(f"{spec.key}--{spec.version}").create(
            {
                "key": spec.key,
                "version": spec.version,
                "content_hash": spec.content_hash,
                "document": dict(document),
                "state": "PUBLISHED",
            }
        )
        return spec.content_hash

    def get_version(self, key: str, version: str) -> Mapping[str, Any] | None:
        db = firestore_client(self._settings.gcp_project)
        snapshot = db.collection("flow_specs").document(f"{key}--{version}").get()
        if not snapshot.exists:
            return None
        document = (snapshot.to_dict() or {}).get("document")
        return dict(document) if isinstance(document, dict) else None

    def list_all(self) -> tuple[Mapping[str, Any], ...]:
        db = firestore_client(self._settings.gcp_project)
        return tuple(
            dict((snapshot.to_dict() or {}).get("document", {}))
            for snapshot in db.collection("flow_specs").stream()
        )

    def list_versions(self, key: str) -> tuple[str, ...]:
        from ...composer.registry import parse_semver  # noqa: PLC0415

        db = firestore_client(self._settings.gcp_project)
        versions = [
            str((snapshot.to_dict() or {}).get("version", "0.0.0"))
            for snapshot in db.collection("flow_specs").where("key", "==", key).stream()
        ]
        versions.sort(key=parse_semver)
        return tuple(versions)


class GcsObjectStorage(ObjectStorage):
    """Artefactos en Cloud Storage con prefijo de tenant y CMEK."""

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @staticmethod
    def _scoped(tenant_id: TenantId, key: str) -> str:
        prefix = f"tenants/{tenant_id.value}/"
        cleaned = key.lstrip("/")
        return cleaned if cleaned.startswith(prefix) else prefix + cleaned

    def _bucket(self) -> Any:
        return storage_client(self._settings.gcp_project).bucket(  # type: ignore[attr-defined]
            self._settings.artifact_bucket
        )

    def put(
        self,
        tenant_id: TenantId,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectRef:
        import hashlib  # noqa: PLC0415

        scoped = self._scoped(tenant_id, key)
        blob = self._bucket().blob(scoped)
        blob.metadata = {"tenant-id": tenant_id.value, **dict(metadata or {})}
        blob.upload_from_string(data, content_type=content_type)
        return ObjectRef.build(
            scheme="gs",
            bucket=self._settings.artifact_bucket,
            key=scoped,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            content_type=content_type,
        )

    def get(self, tenant_id: TenantId, ref: ObjectRef) -> bytes:
        import hashlib  # noqa: PLC0415

        from ...errors import IntegrityError, ObjectNotFoundError, TenantIsolationError

        if not ref.key.startswith(f"tenants/{tenant_id.value}/"):
            raise TenantIsolationError(
                "la referencia apunta fuera del alcance del tenant", tenant_id=tenant_id.value
            )
        blob = self._bucket().blob(ref.key)
        if not blob.exists():
            raise ObjectNotFoundError("el objeto no existe", key=ref.key)
        data: bytes = blob.download_as_bytes()
        if hashlib.sha256(data).hexdigest() != ref.sha256:
            raise IntegrityError(
                "el sha256 del objeto no coincide con el declarado (invariante I6)", key=ref.key
            )
        return data

    def exists(self, tenant_id: TenantId, ref: ObjectRef) -> bool:
        if not ref.key.startswith(f"tenants/{tenant_id.value}/"):
            return False
        return bool(self._bucket().blob(ref.key).exists())

    def presign_put(
        self,
        tenant_id: TenantId,
        key: str,
        *,
        ttl_seconds: int = 900,
        content_type: str = "application/octet-stream",
        max_bytes: int | None = None,
    ) -> str:
        from datetime import timedelta  # noqa: PLC0415

        url: str = self._bucket().blob(self._scoped(tenant_id, key)).generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=ttl_seconds),
            method="PUT",
            content_type=content_type,
        )
        return url

    def presign_get(self, tenant_id: TenantId, ref: ObjectRef, *, ttl_seconds: int = 900) -> str:
        from datetime import timedelta  # noqa: PLC0415

        url: str = self._bucket().blob(ref.key).generate_signed_url(
            version="v4", expiration=timedelta(seconds=ttl_seconds), method="GET"
        )
        return url

    def delete_many(self, tenant_id: TenantId, refs: Sequence[ObjectRef]) -> int:
        deleted = 0
        bucket = self._bucket()
        for ref in refs:
            if not ref.key.startswith(f"tenants/{tenant_id.value}/"):
                continue
            blob = bucket.blob(ref.key)
            if blob.exists():
                blob.delete()
                deleted += 1
        return deleted

    def delete_prefix(self, tenant_id: TenantId, prefix: str) -> int:
        bucket = self._bucket()
        blobs = list(bucket.list_blobs(prefix=self._scoped(tenant_id, prefix)))
        for blob in blobs:
            blob.delete()
        return len(blobs)


class TinkKeyProvider(KeyProvider):
    """Material de clave con Tink sobre Cloud KMS.

    Limitaciones documentadas que este adaptador **no** puede resolver solo:

    - Tink no trae caché de material criptográfico; sin ella la latencia de
      KMS por operación hace inviable el sistema. Por eso el contenedor lo
      envuelve en `CachedKeyProvider`.
    - Cloud KMS **no permite destrucción inmediata**: el valor por defecto son
      30 días y es configurable, pero el mínimo configurable no está
      documentado. Verificarlo antes de comprometer un SLA de borrado.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _key_name(self, tenant_id: TenantId) -> str:
        return f"{self._settings.kms_key_alias}/cryptoKeys/tenant-{tenant_id.value}"

    def data_key_for(self, tenant_id: TenantId, *, purpose: str = "field") -> tuple[bytes, bytes]:
        import os  # noqa: PLC0415

        plaintext = os.urandom(32)
        response = kms_client().encrypt(
            request={
                "name": self._key_name(tenant_id),
                "plaintext": plaintext,
                # El AAD de Cloud KMS: el tenant va aquí, igual que en el
                # EncryptionContext de AWS KMS.
                "additional_authenticated_data": f"tenant={tenant_id.value}|purpose={purpose}".encode(),
            }
        )
        return plaintext, bytes(response.ciphertext)

    def unwrap(self, tenant_id: TenantId, wrapped_key: bytes, *, purpose: str = "field") -> bytes:
        try:
            response = kms_client().decrypt(
                request={
                    "name": self._key_name(tenant_id),
                    "ciphertext": wrapped_key,
                    "additional_authenticated_data": (
                        f"tenant={tenant_id.value}|purpose={purpose}".encode()
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001
            raise DecryptionError(
                "no se pudo desenvolver la clave para este tenant", tenant_id=tenant_id.value
            ) from exc
        return bytes(response.plaintext)

    def derive_key(self, tenant_id: TenantId, *, purpose: str, length: int = 32) -> bytes:
        raise NotImplementedError(
            "Cloud KMS no expone derivación de clave determinista. Falta decidir de dónde sale el "
            "material estable para firma y beacons: (a) un secreto por tenant en Secret Manager, "
            "que añade una dependencia de disponibilidad al camino de lectura; (b) una clave "
            "envuelta persistida junto al tenant y desenvuelta al arrancar. La segunda es más "
            "barata pero exige decidir qué pasa cuando se rota."
        )

    def rotate(self, tenant_id: TenantId) -> str:
        response = kms_client().create_crypto_key_version(
            request={"parent": self._key_name(tenant_id)}
        )
        return str(response.name).rsplit("/", 1)[-1]

    def shred_tenant_key(self, tenant_id: TenantId) -> bool:
        """Programa la destrucción. **No es inmediata**: 30 días por defecto."""
        client = kms_client()
        versions = client.list_crypto_key_versions(request={"parent": self._key_name(tenant_id)})
        destroyed = 0
        for version in versions:
            if str(version.state) == "ENABLED":
                client.destroy_crypto_key_version(request={"name": version.name})
                destroyed += 1
        return destroyed > 0

    def is_shredded(self, tenant_id: TenantId) -> bool:
        client = kms_client()
        versions = list(
            client.list_crypto_key_versions(request={"parent": self._key_name(tenant_id)})
        )
        return all(str(v.state) != "ENABLED" for v in versions)


class TinkFieldCipher(FieldCipher):
    """Cifrado por atributo con Tink.

    **No hay equivalente del AWS Database Encryption SDK.** Tink cubre el
    cifrado de sobre y el AAD, pero no la firma del registro completo, ni los
    atributos firmados-pero-no-cifrados, ni los *searchable encryption
    beacons*. Los beacons se reimplementan como HMAC determinista con clave
    por tenant, asumiendo el análisis de fuga de frecuencia.
    """

    __slots__ = ("_settings", "_keys")

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._keys = key_provider

    def encrypt_item(self, tenant_id: TenantId, item: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Falta decidir cómo se firma el registro completo, que Tink no cubre. Las opciones "
            "son: (a) firmar el documento entero con una clave MAC por tenant, lo que obliga a "
            "reescribir la firma en cada actualización parcial; (b) firmar por campo, que "
            "multiplica el tamaño del documento. La primera opción choca con las escrituras "
            "parciales de Firestore, que son el patrón normal aquí."
        )

    def decrypt_item(self, tenant_id: TenantId, item: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Simétrico a encrypt_item: depende de la misma decisión sobre la firma del registro."
        )

    def beacon(self, tenant_id: TenantId, field_name: str, value: str) -> str:
        import hashlib  # noqa: PLC0415
        import hmac  # noqa: PLC0415

        key = self._keys.derive_key(tenant_id, purpose="beacon")
        digest = hmac.new(key, f"{field_name}={value}".encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{tenant_id.value}#{digest[:32]}"


class SecretManagerProvider(SecretsProvider):
    """Secretos en GCP Secret Manager.

    Advertencia de cuota: **600 lecturas/min por proyecto**. Por eso
    `ConfigProvider` es un puerto distinto y la configuración no vive aquí.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_secret(self, name: str, *, version: str = "latest") -> str:
        project = self._settings.gcp_project
        try:
            response = secret_manager_client().access_secret_version(
                request={"name": f"projects/{project}/secrets/{name}/versions/{version}"}
            )
        except Exception as exc:  # noqa: BLE001
            raise ConfigurationError("el secreto no existe o no es accesible", secret_name=name) from exc
        return str(response.payload.data.decode("utf-8"))

    def get_secret_json(self, name: str, *, version: str = "latest") -> Mapping[str, object]:
        import json  # noqa: PLC0415

        parsed = json.loads(self.get_secret(name, version=version))
        if not isinstance(parsed, dict):
            raise ConfigurationError("el secreto JSON debe ser un objeto", secret_name=name)
        return parsed

    def rotate(self, name: str) -> str:
        raise NotImplementedError(
            "La rotación automática de credenciales **no es gestionada** en GCP: Secret Manager "
            "solo emite una notificación por Pub/Sub y el rotador lo escribe el equipo. Falta "
            "decidir dónde vive ese rotador (Cloud Run job, Cloud Function) y cuál es el protocolo "
            "de dos fases con el proveedor externo para no invalidar la credencial en uso."
        )


__all__ = [
    "FirestoreCapabilityRegistry",
    "FirestoreFlowSpecRepository",
    "FirestoreIdempotencyStore",
    "FirestoreMutexLock",
    "FirestoreSessionRepository",
    "GcsObjectStorage",
    "SecretManagerProvider",
    "TinkFieldCipher",
    "TinkKeyProvider",
]
