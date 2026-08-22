"""Caso de uso: purga de datos por retención y crypto-shredding de tenant.

Tres realidades legales que este caso de uso codifica:

1. **El reloj de retención no arranca en `DECIDED`.** Los plazos AML se
   computan desde la finalización de la relación comercial, y solo el
   requirente sabe cuándo ocurre. Por eso `RETAINED → PURGED` depende de un
   evento externo más el plazo de la jurisdicción, nunca de la fecha de la
   sesión.
2. **Bloqueo no es borrado.** `BLOCKED` corresponde a la limitación del
   tratamiento del art. 18 del GDPR: los datos se conservan pero su
   tratamiento queda restringido a cumplir la obligación legal.
3. **La constancia de que la sesión existió sobrevive.** El log de auditoría
   no se borra: se conserva sin PII. Borrarlo destruiría la prueba de que la
   supresión se ejecutó.

El crypto-shredding es el mecanismo que hace efectivo el borrado cuando el
borrado físico no lo es (copias de seguridad, réplicas, almacenamiento
inmutable). Advertencia operativa: **Cloud KMS no permite destrucción
inmediata** —por defecto 30 días, configurable—, y el mínimo configurable no
está documentado; verificarlo antes de comprometer un SLA de borrado.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..domain.enums import EventType, SessionState
from ..domain.events import AuditChain
from ..domain.value_objects import SessionId, TenantId, utc_now
from ..errors import LockAcquisitionError, ValidationError
from ..observability import correlation_scope, get_logger

if TYPE_CHECKING:  # pragma: no cover
    from ..container import Container

_logger = get_logger("application.purge_tenant_data")

#: Estados de sesión incompleta que se purgan sin esperar plazo AML.
INCOMPLETE_STATES: tuple[SessionState, ...] = (
    SessionState.EXPIRED,
    SessionState.ABANDONED,
    SessionState.CANCELLED,
)

#: Recurso del mutex distribuido de la purga.
PURGE_LOCK_RESOURCE: str = "gdpr-purge"


@dataclass(frozen=True, slots=True)
class PurgeCommand:
    """Petición de purga."""

    tenant_id: str
    principal: str = "svc-gdpr"
    correlation_id: str | None = None
    #: Purga las sesiones incompletas más antiguas que este umbral.
    incomplete_older_than_seconds: int = 604_800
    #: Sesión concreta a purgar, o `None` para el barrido completo.
    session_id: str | None = None
    #: Destruye el material de clave del tenant. **Irreversible.**
    shred_tenant_key: bool = False
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class PurgeResult:
    """Resultado del barrido de purga."""

    tenant_id: str
    sessions_purged: tuple[str, ...]
    objects_deleted: int
    records_deleted: int
    key_shredded: bool
    skipped_blocked: tuple[str, ...]
    dry_run: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "sessions_purged": list(self.sessions_purged),
            "objects_deleted": self.objects_deleted,
            "records_deleted": self.records_deleted,
            "key_shredded": self.key_shredded,
            "skipped_blocked": list(self.skipped_blocked),
            "dry_run": self.dry_run,
        }


class PurgeTenantData:
    """Ejecuta la purga bajo mutex distribuido con token de vallado."""

    __slots__ = ("_c",)

    def __init__(self, container: Container) -> None:
        self._c = container

    def execute(self, command: PurgeCommand) -> PurgeResult:
        tenant_id = TenantId(command.tenant_id)
        with correlation_scope(correlation_id=command.correlation_id, tenant_id=tenant_id.value):
            self._c.authorization.assert_authorized(command.principal, tenant_id, "tenant:purge")

            try:
                token = self._c.locks.acquire(tenant_id, PURGE_LOCK_RESOURCE, ttl_seconds=300)
            except LockAcquisitionError:
                _logger.warning("ya hay una purga en curso para el tenant")
                raise

            try:
                return self._run(tenant_id, command)
            finally:
                self._c.locks.release(tenant_id, PURGE_LOCK_RESOURCE, token)

    # -- Interno -----------------------------------------------------------

    def _run(self, tenant_id: TenantId, command: PurgeCommand) -> PurgeResult:
        now = utc_now()
        candidates = self._candidates(tenant_id, command, now)
        purged: list[str] = []
        blocked: list[str] = []
        objects_deleted = 0
        records_deleted = 0

        for session in candidates:
            if session.state is SessionState.BLOCKED:
                # Limitación del tratamiento (art. 18 GDPR): no se borra.
                blocked.append(session.session_id.value)
                continue
            if command.dry_run:
                purged.append(session.session_id.value)
                continue

            objects_deleted += self._c.storage.delete_prefix(
                tenant_id, f"sessions/{session.session_id.value}/"
            )
            chain = AuditChain(
                tenant_id.value,
                session.session_id.value,
                self._c.sessions.audit_trail(tenant_id, session.session_id),
            )
            self._c.sessions.append_audit_event(
                chain.append(
                    EventType.PURGE_REQUESTED,
                    actor=command.principal,
                    attributes={"previous_state": str(session.state)},
                )
            )
            purged_session = session.purge()
            self._c.sessions.save(purged_session, expected_version=None)
            records_deleted += self._c.sessions.delete_session_data(tenant_id, session.session_id)
            # El log de auditoría **no** se borra: es la prueba de la supresión.
            self._c.sessions.append_audit_event(
                chain.append(
                    EventType.PURGE_COMPLETED,
                    actor=command.principal,
                    attributes={"objects_deleted": objects_deleted},
                )
            )
            purged.append(session.session_id.value)

        key_shredded = False
        if command.shred_tenant_key and not command.dry_run:
            key_shredded = self._c.keys.shred_tenant_key(tenant_id)
            self._c.key_cache.invalidate_prefix(f"{tenant_id.value}:")
            _logger.warning(
                "material de clave del tenant destruido: los datos cifrados son irrecuperables",
                key_shredded=key_shredded,
            )

        self._c.telemetry.increment("sessions_purged", value=len(purged))
        return PurgeResult(
            tenant_id=tenant_id.value,
            sessions_purged=tuple(purged),
            objects_deleted=objects_deleted,
            records_deleted=records_deleted,
            key_shredded=key_shredded,
            skipped_blocked=tuple(blocked),
            dry_run=command.dry_run,
        )

    def _candidates(self, tenant_id: TenantId, command: PurgeCommand, now: datetime) -> list[Any]:
        if command.session_id:
            session = self._c.sessions.find(tenant_id, SessionId(command.session_id))
            if session is None:
                raise ValidationError("la sesión indicada no existe", field="session_id")
            return [session]

        cutoff = now - timedelta(seconds=command.incomplete_older_than_seconds)
        candidates: list[Any] = []
        for state in INCOMPLETE_STATES:
            candidates.extend(
                self._c.sessions.list_by_state(tenant_id, state, limit=500, older_than=cutoff)
            )
        # `RETAINED` solo entra si el requirente ya notificó el fin de la
        # relación comercial; ese evento externo se refleja como atributo.
        for session in self._c.sessions.list_by_state(tenant_id, SessionState.RETAINED, limit=500):
            if session.attributes.get("relationship_ended_at"):
                candidates.append(session)
        candidates.extend(
            self._c.sessions.list_by_state(tenant_id, SessionState.BLOCKED, limit=500)
        )
        return candidates


__all__ = [
    "INCOMPLETE_STATES",
    "PURGE_LOCK_RESOURCE",
    "PurgeCommand",
    "PurgeResult",
    "PurgeTenantData",
]
