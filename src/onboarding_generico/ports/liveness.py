"""Puerto de detección de vivacidad (PAD, ISO/IEC 30107-3).

**Brecha crítica de paridad: no existe liveness facial gestionado en GCP.**
Cloud Vision declara explícitamente que no soporta reconocimiento facial
individual; no hay antispoofing, ni reto de vivacidad, ni SDK de cliente.

Consecuencias asumidas en este diseño:

1. Este puerto **no es puramente de backend**: su implementación en AWS
   incluye un SDK de cliente, de modo que un adaptador GCP exige cambiar el
   frontend. Es trabajo de app móvil o web, no solo de infraestructura.
2. La implementación realista en GCP es un **tercero SaaS con certificación
   iBeta PAD**. Como eso llevaría a tres adaptadores (AWS, SaaS en GCP y
   potencialmente el mismo SaaS en AWS), la recomendación es **usar el SaaS
   en ambas nubes** y eliminar la asimetría de raíz.
3. **No se construye liveness propio con modelos abiertos** para un flujo KYC
   en producción: es riesgo regulatorio, no solo técnico.

El PAD **no se degrada con un proveedor de reserva**: si el proveedor
certificado no responde, la sesión espera o se deriva; no se sustituye por
uno sin certificar.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

from ..domain.value_objects import ObjectRef, TenantId


@dataclass(frozen=True, slots=True)
class LivenessSession:
    """Sesión de liveness creada en el proveedor, para que el SDK la consuma."""

    provider_session_id: str
    client_token: str
    expires_in_seconds: int
    provider_id: str = "unknown"


@dataclass(frozen=True, slots=True)
class LivenessResult:
    """Resultado del reto de vivacidad."""

    score: float
    threshold: float
    passed: bool
    injection_detected: bool = False
    audited_image: ObjectRef | None = None
    provider_id: str = "unknown"
    pad_level: str = "unknown"

    def audit_summary(self) -> dict[str, object]:
        return {
            "score": self.score,
            "threshold": self.threshold,
            "passed": self.passed,
            "injection_detected": self.injection_detected,
            "provider_id": self.provider_id,
            "pad_level": self.pad_level,
        }


class LivenessPort(abc.ABC):
    """Reto de vivacidad con detección de ataque de presentación e inyección."""

    @abc.abstractmethod
    def create_session(self, tenant_id: TenantId, *, ttl_seconds: int = 300) -> LivenessSession:
        """Crea la sesión en el proveedor y devuelve el token para el cliente."""

    @abc.abstractmethod
    def get_result(
        self, tenant_id: TenantId, provider_session_id: str, *, threshold: float = 0.90
    ) -> LivenessResult:
        """Recupera el resultado del reto una vez el cliente lo completó."""


__all__ = ["LivenessPort", "LivenessResult", "LivenessSession"]
