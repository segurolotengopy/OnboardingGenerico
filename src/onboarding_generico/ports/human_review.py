"""Puerto de revisión humana.

**Ambas nubes abandonaron el human-in-the-loop gestionado**: SageMaker A2I no
admite clientes nuevos, Document AI HITL se apagó el 16 de enero de 2025 y
Vertex AI Data Labeling el 3 de octubre de 2024. La recomendación oficial de
Google es contratar un partner.

Paradójicamente eso **simplifica** el diseño: se construye a medida en ambas
nubes (repositorio + cómputo + interfaz + log WORM) y la asimetría desaparece.
Además A2I nunca dio buena trazabilidad regulatoria: sus plantillas de tarea
estaban pensadas para etiquetado de ML, no para decisiones de cumplimiento.

El log de decisiones va a almacenamiento inmutable (**S3 Object Lock** o
**GCS Bucket Lock**), que es lo que un regulador espera.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Mapping, Sequence

from ..domain.enums import DecisionOutcome
from ..domain.value_objects import ObjectRef, SessionId, TenantId


@dataclass(frozen=True, slots=True)
class ReviewCase:
    """Caso en la cola de revisión."""

    case_id: str
    tenant_id: str
    session_id: str
    priority: int
    state: str
    reasons: tuple[str, ...] = ()
    assigned_to: str | None = None
    sla_due_at: datetime | None = None
    resume_token: str = ""
    artifacts: tuple[ObjectRef, ...] = ()
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ReviewResolution:
    """Resolución emitida por un revisor humano."""

    case_id: str
    outcome: DecisionOutcome
    reviewer: str
    notes_digest: str = ""
    resolved_at: datetime | None = None
    evidence_refs: tuple[ObjectRef, ...] = field(default=())


class HumanReviewPort(abc.ABC):
    """Cola de revisión propia, idéntica en AWS y en GCP."""

    @abc.abstractmethod
    def open_case(
        self,
        tenant_id: TenantId,
        session_id: SessionId,
        *,
        reasons: Sequence[str],
        priority: int = 50,
        sla_seconds: int = 86_400,
        resume_token: str = "",
        artifacts: Sequence[ObjectRef] = (),
    ) -> ReviewCase:
        """Crea el caso. `reasons` son códigos estables, nunca texto libre con PII."""

    @abc.abstractmethod
    def next_case(self, tenant_id: TenantId, reviewer: str) -> ReviewCase | None:
        """Asigna el siguiente caso por prioridad y SLA. `None` si la cola está vacía.

        La asignación cambia el estado a `IN_REVIEW`: sin esa distinción no se
        puede medir tiempo de cola frente a tiempo de trabajo, ni detectar
        revisores que acaparan casos.
        """

    @abc.abstractmethod
    def release_case(self, tenant_id: TenantId, case_id: str) -> ReviewCase:
        """Devuelve el caso a la cola (revisor liberado o SLA vencido)."""

    @abc.abstractmethod
    def resolve(
        self,
        tenant_id: TenantId,
        case_id: str,
        *,
        outcome: DecisionOutcome,
        reviewer: str,
        notes_digest: str = "",
    ) -> ReviewResolution:
        """Cierra el caso y sella la resolución en el log inmutable."""

    @abc.abstractmethod
    def get_case(self, tenant_id: TenantId, case_id: str) -> ReviewCase | None:
        """Recupera un caso por identificador dentro del alcance del tenant."""

    @abc.abstractmethod
    def pending_count(self, tenant_id: TenantId) -> Mapping[str, int]:
        """Conteo por estado, para la métrica de cola y las alertas de SLA."""


__all__ = ["HumanReviewPort", "ReviewCase", "ReviewResolution"]
