"""Puertos de persistencia.

**Regla innegociable**: estos puertos exponen *operaciones de dominio*, nunca
primitivas de DynamoDB (`PK`, `SK`, `begins_with`, `ConditionExpression`). Un
puerto acoplado al modelo single-table hace inviable el adaptador de
Firestore, que no tiene consultas de rango sobre clave de ordenación.

La dirección del diseño es deliberadamente **la de GCP**: se asume que la
plataforma *no* aplica aislamiento en el plano de datos, de modo que el
`tenant_id` es un parámetro explícito y obligatorio de toda operación. El
adaptador de AWS añade `dynamodb:LeadingKeys` como refuerzo redundante.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from ..domain.enums import Capability, SessionState
from ..domain.events import AuditEvent
from ..domain.session import OnboardingSession
from ..domain.value_objects import ProviderRef, SessionId, TenantId


class SessionRepository(abc.ABC):
    """Persistencia del agregado `OnboardingSession`.

    El bloqueo optimista es parte del contrato: `save` recibe la versión
    esperada y lanza `ConcurrencyError` si otro escritor avanzó primero.
    """

    @abc.abstractmethod
    def get(self, tenant_id: TenantId, session_id: SessionId) -> OnboardingSession:
        """Carga el agregado completo. Lanza `SessionNotFoundError` si no existe."""

    @abc.abstractmethod
    def find(self, tenant_id: TenantId, session_id: SessionId) -> OnboardingSession | None:
        """Como `get`, pero devuelve `None` en vez de lanzar."""

    @abc.abstractmethod
    def save(
        self, session: OnboardingSession, *, expected_version: int | None = None
    ) -> OnboardingSession:
        """Guarda con bloqueo optimista y devuelve el agregado persistido."""

    @abc.abstractmethod
    def list_by_state(
        self,
        tenant_id: TenantId,
        state: SessionState,
        *,
        limit: int = 50,
        older_than: datetime | None = None,
    ) -> tuple[OnboardingSession, ...]:
        """Sesiones del tenant en un estado dado, de la más antigua a la más nueva."""

    @abc.abstractmethod
    def find_by_external_ref(
        self, tenant_id: TenantId, external_ref: str
    ) -> OnboardingSession | None:
        """Busca por el identificador propio del requirente."""

    @abc.abstractmethod
    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        """Añade un evento al log append-only. Nunca actualiza uno existente."""

    @abc.abstractmethod
    def audit_trail(self, tenant_id: TenantId, session_id: SessionId) -> tuple[AuditEvent, ...]:
        """Reconstruye la traza completa, en orden de secuencia."""

    @abc.abstractmethod
    def delete_session_data(self, tenant_id: TenantId, session_id: SessionId) -> int:
        """Elimina los datos del expediente y devuelve cuántos registros borró.

        **No** borra el log de auditoría: la constancia de que la sesión
        existió y fue purgada sobrevive, sin PII.
        """

    @abc.abstractmethod
    def list_session_ids(self, tenant_id: TenantId, *, limit: int = 1000) -> tuple[SessionId, ...]:
        """Enumera sesiones del tenant. Usado por el trabajo de purga."""


class CapabilityRegistryRepository(abc.ABC):
    """Catálogo de plataforma: qué proveedor cubre qué capacidad, país y documento.

    Vive fuera del alcance de `LeadingKeys` porque no lleva prefijo de tenant.
    El vínculo tenant→proveedor sí es tenant-scoped y se consulta con
    `resolve_provider`.
    """

    @abc.abstractmethod
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
        """Da de alta o actualiza un proveedor en el catálogo."""

    @abc.abstractmethod
    def list_providers(
        self,
        capability: Capability,
        *,
        country: str | None = None,
        document_type: str | None = None,
        only_active: bool = True,
    ) -> tuple[ProviderRef, ...]:
        """Proveedores que cubren la capacidad para ese país y documento."""

    @abc.abstractmethod
    def is_registered(self, capability: Capability, provider_id: str) -> bool:
        """`True` si el proveedor existe en el catálogo (activo o no)."""

    @abc.abstractmethod
    def is_active(self, capability: Capability, provider_id: str) -> bool:
        """`True` si el proveedor está activo."""

    @abc.abstractmethod
    def bind_tenant(
        self,
        tenant_id: TenantId,
        capability: Capability,
        *,
        primary: str,
        fallbacks: Sequence[str] = (),
    ) -> None:
        """Autoriza a un tenant a usar una capacidad con su cadena de proveedores."""

    @abc.abstractmethod
    def resolve_provider(
        self, tenant_id: TenantId, capability: Capability, *, country: str, document_type: str
    ) -> tuple[ProviderRef, ...]:
        """Cadena efectiva (primario + reservas) para el tenant.

        Devuelve una tupla vacía si el tenant no tiene la capacidad
        aprovisionada; el llamador traduce eso a `CapabilityNotProvisioned`.
        """

    @abc.abstractmethod
    def tenant_capabilities(self, tenant_id: TenantId) -> tuple[Capability, ...]:
        """Capacidades autorizadas para el tenant."""


class MutexLock(abc.ABC):
    """Mutex distribuido con TTL y token de vallado (*fencing token*).

    El token de vallado es imprescindible: sin él, un proceso que perdió el
    lock por expiración puede seguir escribiendo. El escritor debe incluir el
    token y el almacén rechazar tokens inferiores al último visto.
    """

    @abc.abstractmethod
    def acquire(self, tenant_id: TenantId, resource: str, *, ttl_seconds: int = 60) -> str:
        """Adquiere el lock y devuelve el token de vallado.

        Lanza `LockAcquisitionError` si otro titular lo mantiene.
        """

    @abc.abstractmethod
    def release(self, tenant_id: TenantId, resource: str, token: str) -> bool:
        """Libera el lock si el token es el vigente. `False` si ya no lo era."""

    @abc.abstractmethod
    def is_held(self, tenant_id: TenantId, resource: str) -> bool:
        """`True` si el lock está tomado y no ha expirado."""


class IdempotencyStore(abc.ABC):
    """Reserva de claves de idempotencia con TTL.

    Es el **único** uso legítimo del TTL del almacén: los ítems del expediente
    nunca llevan `expires_at`, porque su borrado lo gobierna la política de
    retención, no una caducidad técnica.
    """

    @abc.abstractmethod
    def reserve(
        self, tenant_id: TenantId, scope: str, key: str, *, ttl_seconds: int = 86_400
    ) -> bool:
        """`True` si la clave se reservó ahora; `False` si ya existía."""

    @abc.abstractmethod
    def result_for(self, tenant_id: TenantId, scope: str, key: str) -> Mapping[str, Any] | None:
        """Resultado previamente asociado a la clave, si lo hay."""

    @abc.abstractmethod
    def record_result(
        self, tenant_id: TenantId, scope: str, key: str, result: Mapping[str, Any]
    ) -> None:
        """Asocia el resultado a una clave ya reservada."""


class FlowSpecRepository(abc.ABC):
    """Almacén de especificaciones de flujo publicadas (plano de control)."""

    @abc.abstractmethod
    def publish(self, document: Mapping[str, Any]) -> str:
        """Publica una spec y devuelve su hash de contenido. Es inmutable."""

    @abc.abstractmethod
    def get_version(self, key: str, version: str) -> Mapping[str, Any] | None:
        """Recupera una versión concreta por clave de resolución."""

    @abc.abstractmethod
    def list_all(self) -> tuple[Mapping[str, Any], ...]:
        """Todas las specs publicadas. La resolución la hace el registro."""

    @abc.abstractmethod
    def list_versions(self, key: str) -> tuple[str, ...]:
        """Versiones publicadas de una clave, en orden semver ascendente."""


__all__ = [
    "CapabilityRegistryRepository",
    "FlowSpecRepository",
    "IdempotencyStore",
    "MutexLock",
    "SessionRepository",
]
