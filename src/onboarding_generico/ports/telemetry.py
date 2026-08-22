"""Puerto de telemetría.

Se porta sin fricción (CloudWatch / Cloud Monitoring), así que la interfaz se
define libremente. La única restricción es de cumplimiento: **las dimensiones
de una métrica no pueden llevar PII ni alta cardinalidad por titular**. Una
dimensión `subject_ref` convertiría la telemetría en un índice de personas.
"""

from __future__ import annotations

import abc
from typing import Mapping


class TelemetryPort(abc.ABC):
    """Contadores, histogramas y medidores con dimensiones acotadas."""

    @abc.abstractmethod
    def increment(self, name: str, *, value: int = 1, dimensions: Mapping[str, str] | None = None) -> None:
        """Incrementa un contador."""

    @abc.abstractmethod
    def observe(self, name: str, value: float, *, dimensions: Mapping[str, str] | None = None) -> None:
        """Registra una observación en un histograma (latencia, puntuación)."""

    @abc.abstractmethod
    def gauge(self, name: str, value: float, *, dimensions: Mapping[str, str] | None = None) -> None:
        """Fija el valor de un medidor (tamaño de cola, sesiones activas)."""

    @abc.abstractmethod
    def snapshot(self) -> Mapping[str, float]:
        """Estado agregado de las métricas. Base de las aserciones en pruebas."""


#: Dimensiones prohibidas: alta cardinalidad o PII directa.
FORBIDDEN_DIMENSIONS: frozenset[str] = frozenset(
    {"subject_ref", "session_id", "id_number", "email", "phone", "correlation_id"}
)


__all__ = ["FORBIDDEN_DIMENSIONS", "TelemetryPort"]
