"""Repositorios en memoria: sesiones, catálogo, locks, idempotencia y specs.

Funcionales y completos. Sirven para pruebas y desarrollo local, y son la
referencia de comportamiento que deben reproducir los adaptadores de nube:
si una prueba de contrato pasa aquí y falla en DynamoDB, el fallo es del
adaptador, no del contrato.

El aislamiento por tenant se aplica de forma **explícita** en cada operación,
que es como lo hace GCP. El adaptador de AWS añade `LeadingKeys` encima.
"""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime
from typing import Any, Mapping, Sequence

from ...domain.enums import Capability, SessionState
from ...domain.events import AuditEvent
from ...domain.session import OnboardingSession
from ...domain.value_objects import ProviderRef, SessionId, TenantId
from ...errors import ConcurrencyError, LockAcquisitionError, SessionNotFoundError
from ...ports.repository import (
    CapabilityRegistryRepository,
    FlowSpecRepository,
    IdempotencyStore,
    MutexLock,
    SessionRepository,
)


class InMemorySessionRepository(SessionRepository):
    """Repositorio de sesiones con bloqueo optimista real."""

    __slots__ = ("_sessions", "_audit", "_lock")

    def __init__(self) -> None:
        self._sessions: dict[tuple[str, str], OnboardingSession] = {}
        self._audit: dict[tuple[str, str], list[AuditEvent]] = {}
        self._lock = threading.RLock()

    def get(self, tenant_id: TenantId, session_id: SessionId) -> OnboardingSession:
        session = self.find(tenant_id, session_id)
        if session is None:
            raise SessionNotFoundError(
                "la sesión no existe dentro del alcance del tenant",
                tenant_id=tenant_id.value,
                session_id=session_id.value,
            )
        return session

    def find(self, tenant_id: TenantId, session_id: SessionId) -> OnboardingSession | None:
        with self._lock:
            return self._sessions.get((tenant_id.value, session_id.value))

    def save(
        self, session: OnboardingSession, *, expected_version: int | None = None
    ) -> OnboardingSession:
        key = (session.tenant_id.value, session.session_id.value)
        with self._lock:
            current = self._sessions.get(key)
            if expected_version is not None:
                actual = current.version if current is not None else 0
                if actual != expected_version:
                    raise ConcurrencyError(
                        "otro escritor avanzó la versión de la sesión",
                        expected_version=expected_version,
                        actual_version=actual,
                    )
            self._sessions[key] = session
            return session

    def list_by_state(
        self,
        tenant_id: TenantId,
        state: SessionState,
        *,
        limit: int = 50,
        older_than: datetime | None = None,
    ) -> tuple[OnboardingSession, ...]:
        with self._lock:
            matches = [
                s
                for (tid, _), s in self._sessions.items()
                if tid == tenant_id.value
                and s.state is state
                and (older_than is None or s.created_at < older_than)
            ]
        matches.sort(key=lambda s: s.created_at)
        return tuple(matches[:limit])

    def find_by_external_ref(self, tenant_id: TenantId, external_ref: str) -> OnboardingSession | None:
        with self._lock:
            for (tid, _), session in self._sessions.items():
                if tid == tenant_id.value and session.external_ref == external_ref:
                    return session
        return None

    def append_audit_event(self, event: AuditEvent) -> AuditEvent:
        key = (event.tenant_id, event.session_id)
        with self._lock:
            self._audit.setdefault(key, []).append(event)
        return event

    def audit_trail(self, tenant_id: TenantId, session_id: SessionId) -> tuple[AuditEvent, ...]:
        with self._lock:
            events = list(self._audit.get((tenant_id.value, session_id.value), ()))
        events.sort(key=lambda e: e.sequence)
        return tuple(events)

    def delete_session_data(self, tenant_id: TenantId, session_id: SessionId) -> int:
        """Borra el expediente y **conserva** el log de auditoría."""
        with self._lock:
            removed = 1 if self._sessions.pop((tenant_id.value, session_id.value), None) else 0
        return removed

    def list_session_ids(self, tenant_id: TenantId, *, limit: int = 1000) -> tuple[SessionId, ...]:
        with self._lock:
            ids = [SessionId(sid) for (tid, sid) in self._sessions if tid == tenant_id.value]
        return tuple(ids[:limit])


class InMemoryCapabilityRegistry(CapabilityRegistryRepository):
    """Catálogo de plataforma y vínculos tenant→proveedor."""

    __slots__ = ("_catalog", "_bindings", "_lock")

    def __init__(self) -> None:
        self._catalog: dict[tuple[str, str], dict[str, Any]] = {}
        self._bindings: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.RLock()

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
        with self._lock:
            self._catalog[(str(capability), provider.provider_id)] = {
                "provider": provider,
                "countries": tuple(countries),
                "document_types": tuple(document_types),
                "active": active,
                "metadata": dict(metadata or {}),
            }

    def list_providers(
        self,
        capability: Capability,
        *,
        country: str | None = None,
        document_type: str | None = None,
        only_active: bool = True,
    ) -> tuple[ProviderRef, ...]:
        with self._lock:
            entries = [
                entry
                for (cap, _), entry in self._catalog.items()
                if cap == str(capability)
                and (entry["active"] or not only_active)
                and _covers(entry["countries"], country)
                and _covers(entry["document_types"], document_type)
            ]
        return tuple(entry["provider"] for entry in entries)

    def is_registered(self, capability: Capability, provider_id: str) -> bool:
        with self._lock:
            return (str(capability), provider_id) in self._catalog

    def is_active(self, capability: Capability, provider_id: str) -> bool:
        with self._lock:
            entry = self._catalog.get((str(capability), provider_id))
            return bool(entry and entry["active"])

    def bind_tenant(
        self,
        tenant_id: TenantId,
        capability: Capability,
        *,
        primary: str,
        fallbacks: Sequence[str] = (),
    ) -> None:
        with self._lock:
            self._bindings[(tenant_id.value, str(capability))] = {
                "primary": primary,
                "fallbacks": tuple(fallbacks),
            }

    def resolve_provider(
        self, tenant_id: TenantId, capability: Capability, *, country: str, document_type: str
    ) -> tuple[ProviderRef, ...]:
        with self._lock:
            binding = self._bindings.get((tenant_id.value, str(capability)))
            if binding is None:
                return ()
            chain = (binding["primary"], *binding["fallbacks"])
            resolved: list[ProviderRef] = []
            for provider_id in chain:
                entry = self._catalog.get((str(capability), provider_id))
                if entry is None or not entry["active"]:
                    continue
                if not _covers(entry["countries"], country):
                    continue
                if not _covers(entry["document_types"], document_type):
                    continue
                resolved.append(entry["provider"])
        return tuple(resolved)

    def tenant_capabilities(self, tenant_id: TenantId) -> tuple[Capability, ...]:
        with self._lock:
            return tuple(
                Capability(cap) for (tid, cap) in self._bindings if tid == tenant_id.value
            )


def _covers(allowed: Sequence[str], value: str | None) -> bool:
    if value is None or "*" in allowed:
        return True
    return value in allowed


class InMemoryMutexLock(MutexLock):
    """Mutex con TTL y token de vallado monótono.

    El token es un contador global creciente: el escritor lo lleva y el
    almacén rechaza tokens inferiores al último visto. Sin él, un proceso que
    perdió el lock por expiración podría seguir escribiendo.
    """

    __slots__ = ("_locks", "_fence", "_lock", "_clock")

    def __init__(self, clock: Any = None) -> None:
        self._locks: dict[tuple[str, str], tuple[str, float]] = {}
        self._fence = 0
        self._lock = threading.Lock()
        self._clock = clock or time.monotonic

    def acquire(self, tenant_id: TenantId, resource: str, *, ttl_seconds: int = 60) -> str:
        key = (tenant_id.value, resource)
        now = self._clock()
        with self._lock:
            current = self._locks.get(key)
            if current is not None and current[1] > now:
                raise LockAcquisitionError(
                    "el recurso está bloqueado por otro titular",
                    tenant_id=tenant_id.value,
                    resource=resource,
                )
            self._fence += 1
            token = f"fence-{self._fence}"
            self._locks[key] = (token, now + ttl_seconds)
            return token

    def release(self, tenant_id: TenantId, resource: str, token: str) -> bool:
        key = (tenant_id.value, resource)
        with self._lock:
            current = self._locks.get(key)
            if current is None or current[0] != token:
                return False
            self._locks.pop(key, None)
            return True

    def is_held(self, tenant_id: TenantId, resource: str) -> bool:
        key = (tenant_id.value, resource)
        with self._lock:
            current = self._locks.get(key)
            return current is not None and current[1] > self._clock()


class InMemoryIdempotencyStore(IdempotencyStore):
    """Reserva de claves de idempotencia con TTL."""

    __slots__ = ("_entries", "_lock", "_clock")

    def __init__(self, clock: Any = None) -> None:
        self._entries: dict[tuple[str, str, str], tuple[float, dict[str, Any] | None]] = {}
        self._lock = threading.Lock()
        self._clock = clock or time.monotonic

    def reserve(self, tenant_id: TenantId, scope: str, key: str, *, ttl_seconds: int = 86_400) -> bool:
        identity = (tenant_id.value, scope, key)
        now = self._clock()
        with self._lock:
            current = self._entries.get(identity)
            if current is not None and current[0] > now:
                return False
            self._entries[identity] = (now + ttl_seconds, None)
            return True

    def result_for(self, tenant_id: TenantId, scope: str, key: str) -> Mapping[str, Any] | None:
        identity = (tenant_id.value, scope, key)
        with self._lock:
            current = self._entries.get(identity)
            if current is None or current[0] <= self._clock():
                return None
            return copy.deepcopy(current[1]) if current[1] is not None else None

    def record_result(
        self, tenant_id: TenantId, scope: str, key: str, result: Mapping[str, Any]
    ) -> None:
        identity = (tenant_id.value, scope, key)
        with self._lock:
            current = self._entries.get(identity)
            expires = current[0] if current else self._clock() + 86_400
            self._entries[identity] = (expires, dict(result))


class InMemoryFlowSpecRepository(FlowSpecRepository):
    """Almacén de specs publicadas, inmutables por versión."""

    __slots__ = ("_documents", "_lock")

    def __init__(self) -> None:
        self._documents: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()

    def publish(self, document: Mapping[str, Any]) -> str:
        from ...composer.spec import FlowSpec

        spec = FlowSpec.parse(document)
        with self._lock:
            self._documents[(spec.key, spec.version)] = dict(document)
        return spec.content_hash

    def get_version(self, key: str, version: str) -> Mapping[str, Any] | None:
        with self._lock:
            document = self._documents.get((key, version))
            return dict(document) if document else None

    def list_all(self) -> tuple[Mapping[str, Any], ...]:
        with self._lock:
            return tuple(dict(d) for d in self._documents.values())

    def list_versions(self, key: str) -> tuple[str, ...]:
        from ...composer.registry import parse_semver

        with self._lock:
            versions = [v for (k, v) in self._documents if k == key]
        versions.sort(key=parse_semver)
        return tuple(versions)


__all__ = [
    "InMemoryCapabilityRegistry",
    "InMemoryFlowSpecRepository",
    "InMemoryIdempotencyStore",
    "InMemoryMutexLock",
    "InMemorySessionRepository",
]
