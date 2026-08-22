"""Puerto de orquestación de la saga de onboarding.

**El puerto habla el lenguaje del dominio**, nunca el de Step Functions:
no hay `waitForTaskToken`, ni `SendTaskSuccess`, ni `executions.run`. Si el
puerto expusiera esas primitivas, el adaptador de Cloud Workflows sería
inviable.

La forma de la interfaz la dicta GCP, que es el destino más restrictivo:

- Los callbacks de Cloud Workflows tienen un **default de 12 h**, **un solo
  slot pendiente por endpoint** (HTTP 429 al segundo) y **sin heartbeat**.
  Step Functions llega a 1 año con tokens ilimitados y `SendTaskHeartbeat`.
- Por eso `await_manual_decision` **no promete una espera larga en un único
  callback**: devuelve un `ResumeToken` persistible y el adaptador GCP puede
  terminar la ejecución y lanzar una nueva con `resume()`.
- El límite de **512 KB acumulados por ejecución** de Workflows obliga a que
  el contexto de la saga sean punteros, no payloads.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ..domain.value_objects import SessionId, TenantId


@dataclass(frozen=True, slots=True)
class SagaHandle:
    """Referencia a una ejecución de saga en curso."""

    execution_id: str
    tenant_id: str
    session_id: str
    started_at: str
    orchestrator: str = "inmemory"


@dataclass(frozen=True, slots=True)
class ResumeToken:
    """Token opaco para reanudar una saga suspendida.

    Es persistible a propósito: en GCP la ejecución puede haber terminado y la
    reanudación arranca una nueva, así que el token no puede ser un puntero en
    memoria del orquestador.
    """

    value: str
    session_id: str
    tenant_id: str
    expires_at: str
    reason: str = ""


@dataclass(frozen=True, slots=True)
class SagaStatus:
    """Estado observable de la saga."""

    execution_id: str
    state: str
    current_step: str | None = None
    suspended: bool = False
    context: Mapping[str, Any] = field(default_factory=dict)


class OnboardingSagaPort(abc.ABC):
    """Operaciones de dominio de la saga de verificación."""

    @abc.abstractmethod
    def start_verification(
        self,
        tenant_id: TenantId,
        session_id: SessionId,
        *,
        plan: Mapping[str, Any],
        context: Mapping[str, Any] | None = None,
    ) -> SagaHandle:
        """Arranca la verificación con el plan de ejecución compilado.

        `plan` y `context` solo llevan punteros y metadatos: el límite de
        512 KB acumulados de Cloud Workflows es el más restrictivo del diseño.
        """

    @abc.abstractmethod
    def await_manual_decision(
        self,
        handle: SagaHandle,
        *,
        reason: str,
        ttl_seconds: int = 604_800,
    ) -> ResumeToken:
        """Suspende la saga a la espera de una decisión humana.

        Un TTL por defecto de 7 días es deliberado: un caso que escala a
        compliance o cruza un fin de semana no cabe en las 12 h del callback
        de Cloud Workflows, así que el adaptador GCP persiste el estado y
        termina la ejecución.
        """

    @abc.abstractmethod
    def resume(self, token: ResumeToken, payload: Mapping[str, Any]) -> SagaHandle:
        """Reanuda la saga con el resultado de la decisión.

        Debe ser **idempotente**: reanudar dos veces con el mismo token no
        produce dos avances. Firestore + Eventarc no garantiza orden ni
        permite replay, así que los consumidores se diseñan reentrantes.
        """

    @abc.abstractmethod
    def status(self, handle: SagaHandle) -> SagaStatus:
        """Estado actual de la ejecución."""

    @abc.abstractmethod
    def compensate(self, handle: SagaHandle, *, reason: str) -> SagaStatus:
        """Ejecuta las compensaciones de los pasos compensables ya ejecutados.

        Los pasos marcados `compensable: false` (llamada facturable a registro
        oficial, reto de liveness consumido) **no se compensan**: por eso el
        validador advierte cuando aparecen temprano en el DAG.
        """

    @abc.abstractmethod
    def abort(self, handle: SagaHandle, *, reason: str) -> SagaStatus:
        """Aborta la ejecución sin compensar."""


__all__ = ["OnboardingSagaPort", "ResumeToken", "SagaHandle", "SagaStatus"]
