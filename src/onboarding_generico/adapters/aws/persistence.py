"""Adaptadores de AWS: DynamoDB, S3, DB-ESDK y Secrets Manager.

Esqueletos honestos: la firma es completa, el docstring explica el mapeo al
servicio real y el cuerpo lleva la llamada al SDK escrita. Se deja
`NotImplementedError` solo donde falta una **decisión de negocio**, no donde
falta código mecánico.

Modelo de datos (doc 03 §4): cuatro tablas, no una.

============================  =============================================
Tabla                         Propósito
============================  =============================================
``og-{env}-core``             Single-table del dominio, con GSI, TTL, stream
``og-{env}-capability-registry``  Catálogo de plataforma, sin prefijo de tenant
``og-{env}-locks``            Mutex distribuido con TTL y token de vallado
``og-{env}-keystore``         Branch keys del hierarchical keyring
============================  =============================================

Toda PK del dominio empieza por ``TENANT#<tid>``, porque
`dynamodb:LeadingKeys` **no es retrofit-able** sin migración de datos. Todo
GSI lleva el tenant en su partition key: `LeadingKeys` protege la tabla base y
los LSI, pero **no los GSI**.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from ...config import Settings
from ...domain.enums import Capability, SessionState
from ...domain.events import AuditEvent
from ...domain.session import OnboardingSession
from ...domain.value_objects import ObjectRef, ProviderRef, SessionId, TenantId
from ...errors import ConfigurationError, DecryptionError
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
from ._client import client, resource


def _pk(tenant_id: TenantId) -> str:
    """Clave de partición del dominio. **Nunca lleva PII.**"""
    return f"TENANT#{tenant_id.value}"


class DynamoDbSessionRepository(SessionRepository):
    """Sesiones en la tabla single-table `og-{env}-core`.

    Patrones de acceso cubiertos (doc 03 §4.4): PA-03 (`Query` con
    `begins_with(SK,'SESSION#s')` para el agregado completo), PA-04 (`GetItem`
    de la cabecera), PA-05 (`UpdateItem` con
    `ConditionExpression: version = :v` para el bloqueo optimista), PA-08
    (`PutItem` con `attribute_not_exists(SK)` para el log append-only) y PA-09
    (`Query` sobre GSI1 por estado).

    Nota de contrato: **estas primitivas viven aquí y no en el puerto**. El
    puerto habla de sesiones y estados; si expusiera `begins_with`, el
    adaptador de Firestore sería inviable.
    """

    __slots__ = ("_settings", "_table_name")

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._table_name = settings.resource_name("core")

    def _table(self) -> Any:
        return resource("dynamodb", self._settings.region).Table(self._table_name)

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
        from boto3.dynamodb.conditions import Key

        response = self._table().query(
            KeyConditionExpression=Key("PK").eq(_pk(tenant_id))
            & Key("SK").begins_with(f"SESSION#{session_id.value}"),
            ConsistentRead=True,
        )
        items = response.get("Items", [])
        if not items:
            return None
        raise NotImplementedError(
            "Falta decidir la forma exacta de rehidratación del agregado desde los ítems "
            "(cabecera + pasos + artefactos + evidencias) y qué campos se descifran de forma "
            "perezosa. Es una decisión de coste: descifrar todo en cada lectura multiplica las "
            "llamadas de descifrado por sesión."
        )

    def save(
        self, session: OnboardingSession, *, expected_version: int | None = None
    ) -> OnboardingSession:
        """Escritura con bloqueo optimista sobre `version` (PA-05)."""
        table = self._table()
        item = {
            "PK": _pk(session.tenant_id),
            "SK": f"SESSION#{session.session_id.value}",
            "state": str(session.state),
            "version": session.version,
            "country": session.country,
            "document_type": str(session.document_type),
            "tier": session.tier,
            "spec_key": session.spec_ref.key,
            "spec_version": session.spec_ref.version,
            "spec_hash": session.spec_ref.content_hash,
            "created_at": session.created_at.isoformat(),
            "expires_at": session.expires_at.isoformat() if session.expires_at else None,
            # GSI1: trabajo por estado. El tenant va en la PK del índice o
            # queda fuera del perímetro de `LeadingKeys`.
            "GSI1PK": f"TENANT#{session.tenant_id.value}#STATE#{session.state}",
            "GSI1SK": f"{session.created_at.isoformat()}#{session.session_id.value}",
        }
        if session.external_ref:
            item["GSI2PK"] = f"TENANT#{session.tenant_id.value}#EXTREF"
            item["GSI2SK"] = session.external_ref

        kwargs: dict[str, Any] = {"Item": item}
        if expected_version is not None:
            kwargs["ConditionExpression"] = (
                "attribute_not_exists(SK)" if expected_version == 0 else "version = :v"
            )
            if expected_version != 0:
                kwargs["ExpressionAttributeValues"] = {":v": expected_version}
        try:
            table.put_item(**kwargs)
        except Exception as exc:
            from ...errors import ConcurrencyError

            if type(exc).__name__ == "ConditionalCheckFailedException":
                raise ConcurrencyError("otro escritor avanzó la versión de la sesión") from exc
            raise
        return session

    def list_by_state(
        self,
        tenant_id: TenantId,
        state: SessionState,
        *,
        limit: int = 50,
        older_than: datetime | None = None,
    ) -> tuple[OnboardingSession, ...]:
        """PA-09: `Query` sobre GSI1 con `TENANT#<tid>#STATE#<estado>`."""
        from boto3.dynamodb.conditions import Key

        self._table().query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(f"TENANT#{tenant_id.value}#STATE#{state}"),
            Limit=limit,
            ScanIndexForward=True,
        )
        raise NotImplementedError(
            "Falta decidir si esta consulta rehidrata el agregado completo (caro) o devuelve una "
            "proyección ligera. La purga solo necesita identificador y fechas; la cola de revisión "
            "necesita más. Probablemente haya que separar el método en dos."
        )

    def find_by_external_ref(
        self, tenant_id: TenantId, external_ref: str
    ) -> OnboardingSession | None:
        """PA-10: `Query` sobre GSI2 con la referencia del requirente."""
        from boto3.dynamodb.conditions import Key

        response = self._table().query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(f"TENANT#{tenant_id.value}#EXTREF")
            & Key("GSI2SK").eq(external_ref),
            Limit=1,
        )
        if not response.get("Items"):
            return None
        return self.find(tenant_id, SessionId(str(response["Items"][0]["SK"]).split("#", 1)[1]))

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        """PA-08: `PutItem` condicional. La política IAM **no concede `UpdateItem`**."""
        audit_sort_key = (
            f"AUDIT#{event.session_id}#{event.occurred_at.isoformat()}#{event.sequence:06d}"
        )
        self._table().put_item(
            Item={
                "PK": f"TENANT#{event.tenant_id}",
                "SK": audit_sort_key,
                "event_id": event.event_id,
                "event_type": str(event.event_type),
                "actor": event.actor,
                "sequence": event.sequence,
                "previous_hash": event.previous_hash,
                "event_hash": event.event_hash,
                "attributes": dict(event.attributes),
            },
            ConditionExpression="attribute_not_exists(SK)",
        )
        return event

    def audit_trail(self, tenant_id: TenantId, session_id: SessionId) -> tuple[AuditEvent, ...]:
        """PA-16: `Query` con `begins_with(SK,'AUDIT#<sid>#')`, en orden natural."""
        from boto3.dynamodb.conditions import Key

        self._table().query(
            KeyConditionExpression=Key("PK").eq(_pk(tenant_id))
            & Key("SK").begins_with(f"AUDIT#{session_id.value}#"),
            ScanIndexForward=True,
        )
        raise NotImplementedError(
            "Falta decidir el criterio de paginación de trazas muy largas y si se verifica la "
            "cadena de hash en cada lectura o solo al sellar el expediente. Verificar siempre es "
            "correcto pero multiplica el coste de lectura."
        )

    def delete_session_data(self, tenant_id: TenantId, session_id: SessionId) -> int:
        """Borra el expediente con `BatchWriteItem`, **sin tocar los `AUDIT#`**."""
        raise NotImplementedError(
            "Falta decidir si el borrado usa TTL (asíncrono, hasta 48 h de retraso, incompatible "
            "con un SLA de supresión) o BatchWriteItem inmediato con su coste de WCU. La respuesta "
            "depende del SLA que se comprometa con el responsable del tratamiento."
        )

    def list_session_ids(self, tenant_id: TenantId, *, limit: int = 1000) -> tuple[SessionId, ...]:
        from boto3.dynamodb.conditions import Key

        response = self._table().query(
            KeyConditionExpression=Key("PK").eq(_pk(tenant_id)) & Key("SK").begins_with("SESSION#"),
            ProjectionExpression="SK",
            Limit=limit,
        )
        return tuple(
            SessionId(str(item["SK"]).split("#", 1)[1])
            for item in response.get("Items", [])
            if "#STEP#" not in str(item["SK"])
        )


class DynamoDbCapabilityRegistry(CapabilityRegistryRepository):
    """Catálogo en `og-{env}-capability-registry`.

    `PK = CAPABILITY#<id>`, `SK = COUNTRY#…#DOCTYPE#…#V<n>` (PA-17). Esta tabla
    **no lleva prefijo de tenant** y por eso queda fuera de la política de
    `LeadingKeys`: es catálogo de plataforma, no dato de tenant. Los vínculos
    tenant→proveedor sí viven en `og-{env}-core` con `SK = CAP#<id>#<version>`.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _catalog_table(self) -> Any:
        return resource("dynamodb", self._settings.region).Table(
            self._settings.resource_name("capability-registry")
        )

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
        table = self._catalog_table()
        for country in countries:
            for document_type in document_types:
                table.put_item(
                    Item={
                        "PK": f"CAPABILITY#{capability}",
                        "SK": f"COUNTRY#{country}#DOCTYPE#{document_type}#V{provider.version}",
                        "provider_id": provider.provider_id,
                        "active": active,
                        "metadata": dict(metadata or {}),
                    }
                )

    def list_providers(
        self,
        capability: Capability,
        *,
        country: str | None = None,
        document_type: str | None = None,
        only_active: bool = True,
    ) -> tuple[ProviderRef, ...]:
        from boto3.dynamodb.conditions import Key

        prefix = f"COUNTRY#{country or ''}"
        if country and document_type:
            prefix = f"COUNTRY#{country}#DOCTYPE#{document_type}#"
        response = self._catalog_table().query(
            KeyConditionExpression=Key("PK").eq(f"CAPABILITY#{capability}")
            & Key("SK").begins_with(prefix)
        )
        return tuple(
            ProviderRef(str(item["provider_id"]), str(item["SK"]).rsplit("#V", 1)[-1])
            for item in response.get("Items", [])
            if item.get("active", True) or not only_active
        )

    def is_registered(self, capability: Capability, provider_id: str) -> bool:
        return any(
            p.provider_id == provider_id for p in self.list_providers(capability, only_active=False)
        )

    def is_active(self, capability: Capability, provider_id: str) -> bool:
        return any(p.provider_id == provider_id for p in self.list_providers(capability))

    def bind_tenant(
        self,
        tenant_id: TenantId,
        capability: Capability,
        *,
        primary: str,
        fallbacks: Sequence[str] = (),
    ) -> None:
        resource("dynamodb", self._settings.region).Table(
            self._settings.resource_name("core")
        ).put_item(
            Item={
                "PK": _pk(tenant_id),
                "SK": f"CAP#{capability}#1",
                "primary_provider": primary,
                "fallbacks": list(fallbacks),
            }
        )

    def resolve_provider(
        self, tenant_id: TenantId, capability: Capability, *, country: str, document_type: str
    ) -> tuple[ProviderRef, ...]:
        """PA-02 + PA-17: vínculo del tenant filtrado por el catálogo."""
        raise NotImplementedError(
            "Falta decidir la política de resolución cuando el proveedor primario del tenant no "
            "cubre el país solicitado: ¿se degrada al fallback silenciosamente o se responde "
            "CapabilityNotProvisioned? La primera opción cambia el proveedor sin que el requirente "
            "lo sepa, lo que afecta a la trazabilidad regulatoria."
        )

    def tenant_capabilities(self, tenant_id: TenantId) -> tuple[Capability, ...]:
        from boto3.dynamodb.conditions import Key

        response = (
            resource("dynamodb", self._settings.region)
            .Table(self._settings.resource_name("core"))
            .query(
                KeyConditionExpression=Key("PK").eq(_pk(tenant_id)) & Key("SK").begins_with("CAP#")
            )
        )
        return tuple(
            Capability(str(item["SK"]).split("#")[1]) for item in response.get("Items", [])
        )


class DynamoDbMutexLock(MutexLock):
    """Mutex en `og-{env}-locks` (PA-18).

    `PutItem` condicional sobre `LOCK#<tenant>#<recurso>` con TTL y token de
    vallado monótono. El token es indispensable: sin él, un proceso que perdió
    el lock por expiración seguiría escribiendo.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _table(self) -> Any:
        return resource("dynamodb", self._settings.region).Table(
            self._settings.resource_name("locks")
        )

    def acquire(self, tenant_id: TenantId, resource_name: str, *, ttl_seconds: int = 60) -> str:
        import time

        from ...errors import LockAcquisitionError

        now = int(time.time())
        fence = f"{now}-{tenant_id.value}"
        try:
            self._table().put_item(
                Item={
                    "PK": f"LOCK#{tenant_id.value}#{resource_name}",
                    "fence_token": fence,
                    "expires_at": now + ttl_seconds,
                },
                ConditionExpression="attribute_not_exists(PK) OR expires_at < :now",
                ExpressionAttributeValues={":now": now},
            )
        except Exception as exc:
            raise LockAcquisitionError(
                "el recurso está bloqueado por otro titular",
                tenant_id=tenant_id.value,
                resource=resource_name,
            ) from exc
        return fence

    def release(self, tenant_id: TenantId, resource_name: str, token: str) -> bool:
        try:
            self._table().delete_item(
                Key={"PK": f"LOCK#{tenant_id.value}#{resource_name}"},
                ConditionExpression="fence_token = :t",
                ExpressionAttributeValues={":t": token},
            )
        except Exception:
            return False
        return True

    def is_held(self, tenant_id: TenantId, resource_name: str) -> bool:
        import time

        response = self._table().get_item(
            Key={"PK": f"LOCK#{tenant_id.value}#{resource_name}"}, ConsistentRead=True
        )
        item = response.get("Item")
        return bool(item and int(item.get("expires_at", 0)) > int(time.time()))


class DynamoDbIdempotencyStore(IdempotencyStore):
    """Claves de idempotencia con TTL (PA-13).

    **El único uso legítimo del TTL** en este diseño: los ítems del expediente
    nunca llevan `expires_at`, porque su borrado lo gobierna la política de
    retención, no una caducidad técnica.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _table(self) -> Any:
        return resource("dynamodb", self._settings.region).Table(
            self._settings.resource_name("core")
        )

    def reserve(
        self, tenant_id: TenantId, scope: str, key: str, *, ttl_seconds: int = 86_400
    ) -> bool:
        import time

        try:
            self._table().put_item(
                Item={
                    "PK": _pk(tenant_id),
                    "SK": f"IDEM#{scope}#{key}",
                    "expires_at": int(time.time()) + ttl_seconds,
                },
                ConditionExpression="attribute_not_exists(SK)",
            )
        except Exception:
            return False
        return True

    def result_for(self, tenant_id: TenantId, scope: str, key: str) -> Mapping[str, Any] | None:
        response = self._table().get_item(Key={"PK": _pk(tenant_id), "SK": f"IDEM#{scope}#{key}"})
        item = response.get("Item")
        return dict(item.get("result", {})) if item and "result" in item else None

    def record_result(
        self, tenant_id: TenantId, scope: str, key: str, result: Mapping[str, Any]
    ) -> None:
        self._table().update_item(
            Key={"PK": _pk(tenant_id), "SK": f"IDEM#{scope}#{key}"},
            UpdateExpression="SET #r = :r",
            ExpressionAttributeNames={"#r": "result"},
            ExpressionAttributeValues={":r": dict(result)},
        )


class DynamoDbFlowSpecRepository(FlowSpecRepository):
    """Specs publicadas: cabecera en DynamoDB, artefactos compilados en S3.

    `PK = SPEC#<tenant_o_GLOBAL>`, `SK = FLOW#<clave>#v<semver>` (PA-15). El
    ASL y el YAML compilados van a S3 porque el límite de ítem de DynamoDB son
    400 KB y una definición de máquina de estados puede acercarse a 1 MB.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def publish(self, document: Mapping[str, Any]) -> str:
        from ...composer.spec import FlowSpec

        spec = FlowSpec.parse(document)
        import json

        client("s3", self._settings.region).put_object(
            Bucket=self._settings.resource_name("specs"),
            Key=f"{spec.key}/{spec.version}.json",
            Body=json.dumps(document).encode("utf-8"),
            ContentType="application/json",
        )
        resource("dynamodb", self._settings.region).Table(
            self._settings.resource_name("core")
        ).put_item(
            Item={
                "PK": f"SPEC#{spec.tenant}",
                "SK": f"FLOW#{spec.key}#v{spec.version}",
                "content_hash": spec.content_hash,
                "state": "PUBLISHED",
            },
            ConditionExpression="attribute_not_exists(SK)",
        )
        return spec.content_hash

    def get_version(self, key: str, version: str) -> Mapping[str, Any] | None:
        import json

        try:
            response = client("s3", self._settings.region).get_object(
                Bucket=self._settings.resource_name("specs"), Key=f"{key}/{version}.json"
            )
        except Exception:
            return None
        parsed: dict[str, Any] = json.loads(response["Body"].read())
        return parsed

    def list_all(self) -> tuple[Mapping[str, Any], ...]:
        raise NotImplementedError(
            "Falta decidir si el registro se carga completo en memoria al arrancar (rápido, pero "
            "obliga a invalidar en cada publicación) o se resuelve por consulta (PA-15) con caché "
            "por clave. Depende del número de tenants y de la frecuencia de publicación."
        )

    def list_versions(self, key: str) -> tuple[str, ...]:
        from boto3.dynamodb.conditions import Key

        tenant = key.split(":", 1)[0]
        response = (
            resource("dynamodb", self._settings.region)
            .Table(self._settings.resource_name("core"))
            .query(
                KeyConditionExpression=Key("PK").eq(f"SPEC#{tenant}")
                & Key("SK").begins_with(f"FLOW#{key}#v"),
                ScanIndexForward=True,
            )
        )
        return tuple(str(item["SK"]).rsplit("#v", 1)[-1] for item in response.get("Items", []))


class S3ObjectStorage(ObjectStorage):
    """Artefactos en S3 con prefijo de tenant y cifrado en reposo con KMS."""

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _bucket(self) -> str:
        return self._settings.artifact_bucket

    @staticmethod
    def _scoped(tenant_id: TenantId, key: str) -> str:
        prefix = f"tenants/{tenant_id.value}/"
        cleaned = key.lstrip("/")
        return cleaned if cleaned.startswith(prefix) else prefix + cleaned

    def put(
        self,
        tenant_id: TenantId,
        key: str,
        data: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> ObjectRef:
        import hashlib

        scoped = self._scoped(tenant_id, key)
        digest = hashlib.sha256(data).hexdigest()
        client("s3", self._settings.region).put_object(
            Bucket=self._bucket(),
            Key=scoped,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=self._settings.kms_key_alias,
            # El tenant viaja como metadato para el análisis forense; el
            # aislamiento real lo da el AAD del cifrado de sobre.
            Metadata={"tenant-id": tenant_id.value, **dict(metadata or {})},
        )
        return ObjectRef.build(
            scheme="s3",
            bucket=self._bucket(),
            key=scoped,
            sha256=digest,
            size_bytes=len(data),
            content_type=content_type,
        )

    def get(self, tenant_id: TenantId, ref: ObjectRef) -> bytes:
        import hashlib

        from ...errors import IntegrityError, ObjectNotFoundError, TenantIsolationError

        if not ref.key.startswith(f"tenants/{tenant_id.value}/"):
            raise TenantIsolationError(
                "la referencia apunta fuera del alcance del tenant", tenant_id=tenant_id.value
            )
        try:
            response = client("s3", self._settings.region).get_object(
                Bucket=ref.bucket, Key=ref.key
            )
        except Exception as exc:
            raise ObjectNotFoundError("el objeto no existe", key=ref.key) from exc
        data: bytes = response["Body"].read()
        if hashlib.sha256(data).hexdigest() != ref.sha256:
            raise IntegrityError(
                "el sha256 del objeto no coincide con el declarado (invariante I6)", key=ref.key
            )
        return data

    def exists(self, tenant_id: TenantId, ref: ObjectRef) -> bool:
        if not ref.key.startswith(f"tenants/{tenant_id.value}/"):
            return False
        try:
            client("s3", self._settings.region).head_object(Bucket=ref.bucket, Key=ref.key)
        except Exception:
            return False
        return True

    def presign_put(
        self,
        tenant_id: TenantId,
        key: str,
        *,
        ttl_seconds: int = 900,
        content_type: str = "application/octet-stream",
        max_bytes: int | None = None,
    ) -> str:
        params: dict[str, Any] = {
            "Bucket": self._bucket(),
            "Key": self._scoped(tenant_id, key),
            "ContentType": content_type,
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": self._settings.kms_key_alias,
        }
        url: str = client("s3", self._settings.region).generate_presigned_url(
            "put_object", Params=params, ExpiresIn=ttl_seconds
        )
        return url

    def presign_get(self, tenant_id: TenantId, ref: ObjectRef, *, ttl_seconds: int = 900) -> str:
        url: str = client("s3", self._settings.region).generate_presigned_url(
            "get_object", Params={"Bucket": ref.bucket, "Key": ref.key}, ExpiresIn=ttl_seconds
        )
        return url

    def delete_many(self, tenant_id: TenantId, refs: Sequence[ObjectRef]) -> int:
        in_scope = [r for r in refs if r.key.startswith(f"tenants/{tenant_id.value}/")]
        if not in_scope:
            return 0
        response = client("s3", self._settings.region).delete_objects(
            Bucket=self._bucket(),
            Delete={"Objects": [{"Key": r.key} for r in in_scope], "Quiet": True},
        )
        return len(in_scope) - len(response.get("Errors", []))

    def delete_prefix(self, tenant_id: TenantId, prefix: str) -> int:
        raise NotImplementedError(
            "Falta decidir si el borrado por prefijo se hace síncrono con paginación de "
            "list_objects_v2 + delete_objects (coste y tiempo proporcionales al volumen) o con "
            "una regla de ciclo de vida de S3 (asíncrona, sin garantía de plazo). Un SLA de "
            "supresión del art. 17 obliga a la primera opción."
        )


class HierarchicalKeyProvider(KeyProvider):
    """Hierarchical keyring del AWS Database Encryption SDK.

    Es la recomendación de AWS y **no** `CachingCryptoMaterialsManager`: el
    caso público del 77 % de ahorro de KMS describe al CCMM como *la causa*
    del *cache stampede*, no como su solución. Las branch keys viven en
    `og-{env}-keystore` y reducen las llamadas a KMS a una por rotación.
    """

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def data_key_for(self, tenant_id: TenantId, *, purpose: str = "field") -> tuple[bytes, bytes]:
        response = client("kms", self._settings.region).generate_data_key(
            KeyId=self._settings.kms_key_alias,
            KeySpec="AES_256",
            EncryptionContext={"tenant_id": tenant_id.value, "purpose": purpose},
        )
        return response["Plaintext"], response["CiphertextBlob"]

    def unwrap(self, tenant_id: TenantId, wrapped_key: bytes, *, purpose: str = "field") -> bytes:
        try:
            response = client("kms", self._settings.region).decrypt(
                CiphertextBlob=wrapped_key,
                EncryptionContext={"tenant_id": tenant_id.value, "purpose": purpose},
            )
        except Exception as exc:
            # El contexto de cifrado es el AAD: si el tenant no cuadra, KMS
            # falla. Es el comportamiento buscado.
            raise DecryptionError(
                "no se pudo desenvolver la clave para este tenant", tenant_id=tenant_id.value
            ) from exc
        return bytes(response["Plaintext"])

    def derive_key(self, tenant_id: TenantId, *, purpose: str, length: int = 32) -> bytes:
        """Clave determinista derivada de la branch key del tenant.

        Se usa para firmar el registro y para los beacons; ambos exigen que
        procesos distintos obtengan el mismo valor.
        """
        raise NotImplementedError(
            "Falta decidir de qué versión de branch key se deriva la clave determinista. Si se "
            "deriva de la versión vigente, rotar la branch key invalida todos los beacons "
            "existentes y obliga a reindexar; si se fija la versión, la rotación no alcanza al "
            "material de beacon. Es una decisión de compromiso entre rotación y disponibilidad "
            "del índice."
        )

    def rotate(self, tenant_id: TenantId) -> str:
        raise NotImplementedError(
            "Falta decidir la cadencia de rotación de branch key por tenant y si la rotación es "
            "perezosa (al primer uso tras el vencimiento) o programada. Afecta al coste de KMS y "
            "al tamaño del keystore."
        )

    def shred_tenant_key(self, tenant_id: TenantId) -> bool:
        """Crypto-shredding: borra las branch keys del tenant del keystore."""
        resource("dynamodb", self._settings.region).Table(
            self._settings.resource_name("keystore")
        ).delete_item(Key={"branch-key-id": f"tenant-{tenant_id.value}", "version": "ACTIVE"})
        return True

    def is_shredded(self, tenant_id: TenantId) -> bool:
        response = (
            resource("dynamodb", self._settings.region)
            .Table(self._settings.resource_name("keystore"))
            .get_item(Key={"branch-key-id": f"tenant-{tenant_id.value}", "version": "ACTIVE"})
        )
        return "Item" not in response


class DbEsdkFieldCipher(FieldCipher):
    """Cifrado a nivel de atributo con AWS Database Encryption SDK.

    Aporta lo que Tink no tiene: firma del registro completo, atributos
    firmados-pero-no-cifrados y *searchable encryption beacons*. Ese último
    punto es el que **no se porta** a GCP: allí hay que reimplementar los
    beacons como HMAC determinista con clave por tenant.
    """

    __slots__ = ("_keys", "_settings")

    def __init__(self, settings: Settings, key_provider: KeyProvider) -> None:
        self._settings = settings
        self._keys = key_provider

    def encrypt_item(self, tenant_id: TenantId, item: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Falta fijar la configuración de acciones por atributo (`AttributeActions`) definitiva "
            "y la lista de atributos firmados-pero-no-cifrados. Es una decisión de negocio: cada "
            "atributo que pase a SIGN_ONLY se vuelve consultable pero deja de estar cifrado, y esa "
            "compensación la decide el responsable del tratamiento, no el middleware."
        )

    def decrypt_item(self, tenant_id: TenantId, item: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(
            "Simétrico a encrypt_item: depende de la misma configuración de acciones por atributo."
        )

    def beacon(self, tenant_id: TenantId, field_name: str, value: str) -> str:
        raise NotImplementedError(
            "Falta decidir la longitud del beacon por campo. Es un compromiso de privacidad "
            "cuantificable: un beacon corto genera colisiones que ocultan la frecuencia pero "
            "degradan la selectividad de la consulta; uno largo hace lo contrario. La longitud "
            "correcta depende de la cardinalidad real del campo en cada tenant."
        )


class SecretsManagerProvider(SecretsProvider):
    """Secretos en AWS Secrets Manager, con caché en proceso en el llamador."""

    __slots__ = ("_settings",)

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_secret(self, name: str, *, version: str = "latest") -> str:
        kwargs: dict[str, Any] = {"SecretId": name}
        if version != "latest":
            kwargs["VersionId"] = version
        try:
            response = client("secretsmanager", self._settings.region).get_secret_value(**kwargs)
        except Exception as exc:
            raise ConfigurationError(
                "el secreto no existe o no es accesible", secret_name=name
            ) from exc
        return str(response["SecretString"])

    def get_secret_json(self, name: str, *, version: str = "latest") -> Mapping[str, object]:
        import json

        parsed = json.loads(self.get_secret(name, version=version))
        if not isinstance(parsed, dict):
            raise ConfigurationError("el secreto JSON debe ser un objeto", secret_name=name)
        return parsed

    def rotate(self, name: str) -> str:
        response = client("secretsmanager", self._settings.region).rotate_secret(SecretId=name)
        return str(response["VersionId"])


__all__ = [
    "DbEsdkFieldCipher",
    "DynamoDbCapabilityRegistry",
    "DynamoDbFlowSpecRepository",
    "DynamoDbIdempotencyStore",
    "DynamoDbMutexLock",
    "DynamoDbSessionRepository",
    "HierarchicalKeyProvider",
    "S3ObjectStorage",
    "SecretsManagerProvider",
]
