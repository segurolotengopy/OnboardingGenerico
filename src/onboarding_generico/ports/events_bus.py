"""Puerto de bus de eventos de integración.

Diseñado contra la **brecha 6** de paridad: Firestore + Eventarc **no
garantiza orden** ni permite *replay*, mientras que DynamoDB Streams garantiza
orden por clave de partición y retiene 24 h. En consecuencia:

- Todo evento lleva un `sequence` explícito por sesión, para que el consumidor
  reordene sin depender de la plataforma.
- Todo consumidor debe ser **idempotente y reentrante**: `event_id` es la
  clave de deduplicación.
- Para reprocesar no se itera el stream, se itera la colección.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..domain.value_objects import TenantId


@dataclass(frozen=True, slots=True)
class IntegrationEvent:
    """Evento publicado hacia el exterior. **Sin PII en el payload.**"""

    event_id: str
    event_type: str
    tenant_id: str
    session_id: str
    sequence: int
    occurred_at: str
    payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def ordering_key(self) -> str:
        """Clave de ordenación de Pub/Sub: agrupa por sesión."""
        return f"{self.tenant_id}/{self.session_id}"


class EventBusPort(abc.ABC):
    """Publicación de eventos de integración."""

    @abc.abstractmethod
    def publish(self, event: IntegrationEvent) -> str:
        """Publica un evento y devuelve el identificador del mensaje."""

    @abc.abstractmethod
    def publish_batch(self, events: Sequence[IntegrationEvent]) -> tuple[str, ...]:
        """Publica en lote conservando el orden de la secuencia."""

    @abc.abstractmethod
    def published_for(self, tenant_id: TenantId, session_id: str) -> tuple[IntegrationEvent, ...]:
        """Eventos publicados de una sesión, ordenados por `sequence`.

        En producción solo lo implementa el adaptador en memoria; en la nube
        el reproceso se hace iterando la colección, no el stream.
        """


__all__ = ["EventBusPort", "IntegrationEvent"]
