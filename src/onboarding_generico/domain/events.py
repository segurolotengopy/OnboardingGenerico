"""Log de auditoría append-only con cadena de hash.

Cada `AuditEvent` incluye el hash del evento anterior de la misma sesión
(invariante I8). Alterar o eliminar un evento intermedio rompe la cadena y
`verify_chain` lo detecta.

Dos decisiones de diseño que conviene explicitar:

1. **El hash cubre el evento completo**, incluido `previous_hash`. Es lo que
   hace que la cadena sea una cadena y no una lista de hashes independientes.
2. **La serialización es canónica**: JSON con claves ordenadas, separadores
   sin espacios y `ensure_ascii=False`. Sin canonicalización, dos procesos
   que serialicen el mismo evento producirían hashes distintos.

El log **no debe contener PII en claro**. `AuditEvent.create` aplica la misma
redacción que el logger estructurado a los atributos recibidos.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from ..errors import AuditChainError
from ..observability import redact
from .enums import EventType
from .value_objects import utc_now

#: Hash del eslabón cero. Marca el inicio de la cadena de una sesión.
GENESIS_HASH: str = "sha256:" + "0" * 64


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Serialización canónica y estable de un diccionario."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Evento inmutable del log append-only."""

    event_id: str
    tenant_id: str
    session_id: str
    event_type: EventType
    actor: str
    occurred_at: datetime
    sequence: int
    previous_hash: str
    event_hash: str
    attributes: Mapping[str, Any] = field(default_factory=dict)

    # -- Construcción -----------------------------------------------------

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        session_id: str,
        event_type: EventType,
        actor: str,
        previous: AuditEvent | None = None,
        attributes: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
    ) -> AuditEvent:
        """Crea el siguiente eslabón de la cadena de una sesión.

        `attributes` pasa por la misma redacción que el logger: el log de
        auditoría es un artefacto de cumplimiento, no un volcado de datos.
        """
        previous_hash = previous.event_hash if previous is not None else GENESIS_HASH
        sequence = previous.sequence + 1 if previous is not None else 0
        if previous is not None and previous.session_id != session_id:
            raise AuditChainError(
                "el evento previo pertenece a otra sesión",
                expected_session=session_id,
                actual_session=previous.session_id,
            )

        safe_attributes = redact(dict(attributes or {}))
        body = {
            "event_id": event_id or uuid4().hex,
            "tenant_id": tenant_id,
            "session_id": session_id,
            "event_type": str(event_type),
            "actor": actor,
            "occurred_at": (occurred_at or utc_now()).isoformat(),
            "sequence": sequence,
            "previous_hash": previous_hash,
            "attributes": safe_attributes,
        }
        digest = "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()
        return cls(
            event_id=body["event_id"],
            tenant_id=tenant_id,
            session_id=session_id,
            event_type=event_type,
            actor=actor,
            occurred_at=datetime.fromisoformat(body["occurred_at"]),
            sequence=sequence,
            previous_hash=previous_hash,
            event_hash=digest,
            attributes=safe_attributes,
        )

    # -- Verificación -----------------------------------------------------

    def body(self) -> dict[str, Any]:
        """Cuerpo canónico sobre el que se calculó `event_hash`."""
        return {
            "event_id": self.event_id,
            "tenant_id": self.tenant_id,
            "session_id": self.session_id,
            "event_type": str(self.event_type),
            "actor": self.actor,
            "occurred_at": self.occurred_at.isoformat(),
            "sequence": self.sequence,
            "previous_hash": self.previous_hash,
            "attributes": dict(self.attributes),
        }

    def recompute_hash(self) -> str:
        return "sha256:" + hashlib.sha256(canonical_json(self.body()).encode("utf-8")).hexdigest()

    def is_intact(self) -> bool:
        """`True` si el evento no fue alterado tras su creación."""
        return self.recompute_hash() == self.event_hash

    def as_dict(self) -> dict[str, Any]:
        data = self.body()
        data["event_hash"] = self.event_hash
        return data


class AuditChain:
    """Cadena de auditoría en memoria de una sesión.

    Los adaptadores de persistencia guardan los eventos; esta clase encapsula
    la lógica de encadenado y verificación, que es de dominio y no debe
    duplicarse en DynamoDB y en Firestore.
    """

    __slots__ = ("_events", "session_id", "tenant_id")

    def __init__(self, tenant_id: str, session_id: str, events: Iterable[AuditEvent] = ()) -> None:
        self.tenant_id = tenant_id
        self.session_id = session_id
        self._events: list[AuditEvent] = list(events)

    def __len__(self) -> int:
        return len(self._events)

    def __iter__(self) -> Any:
        return iter(self._events)

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    @property
    def head(self) -> AuditEvent | None:
        return self._events[-1] if self._events else None

    @property
    def head_hash(self) -> str:
        head = self.head
        return head.event_hash if head is not None else GENESIS_HASH

    def append(
        self,
        event_type: EventType,
        *,
        actor: str,
        attributes: Mapping[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> AuditEvent:
        """Añade un evento encadenado al final. Nunca modifica los anteriores."""
        event = AuditEvent.create(
            tenant_id=self.tenant_id,
            session_id=self.session_id,
            event_type=event_type,
            actor=actor,
            previous=self.head,
            attributes=attributes,
            occurred_at=occurred_at,
        )
        self._events.append(event)
        return event

    def verify(self) -> None:
        """Lanza `AuditChainError` si la cadena no es íntegra."""
        verify_chain(self._events)

    def manifest(self) -> str:
        """Hash de la cadena completa: el sello del expediente."""
        digest = hashlib.sha256()
        for event in self._events:
            digest.update(event.event_hash.encode("utf-8"))
        return "sha256:" + digest.hexdigest()


def verify_chain(events: Sequence[AuditEvent]) -> None:
    """Verifica integridad, encadenado y numeración de una secuencia.

    Detecta las tres manipulaciones posibles: alterar un evento (cambia su
    hash), eliminar uno (rompe el enlace del siguiente) e insertar uno
    (rompe la numeración).
    """
    expected_previous = GENESIS_HASH
    for index, event in enumerate(events):
        if not event.is_intact():
            raise AuditChainError(
                "evento de auditoría alterado",
                sequence=event.sequence,
                event_id=event.event_id,
            )
        if event.sequence != index:
            raise AuditChainError(
                "numeración de secuencia inconsistente",
                expected=index,
                actual=event.sequence,
            )
        if event.previous_hash != expected_previous:
            raise AuditChainError(
                "cadena de hash rota",
                sequence=event.sequence,
                expected_previous=expected_previous,
                actual_previous=event.previous_hash,
            )
        expected_previous = event.event_hash


__all__ = [
    "GENESIS_HASH",
    "AuditChain",
    "AuditEvent",
    "canonical_json",
    "verify_chain",
]
