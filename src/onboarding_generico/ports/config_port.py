"""Puerto de configuración por tenant y de plataforma.

Separado de `SecretsProvider` por la brecha 9 de la referencia de paridad GCP.
En AWS lo implementa Parameter Store; en GCP, variables de entorno inyectadas
por Terraform o un documento de configuración con caché en proceso.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping
from typing import Any

from ..domain.enums import DecisionIssuer
from ..domain.value_objects import TenantId


class ConfigProvider(abc.ABC):
    """Configuración no secreta, cacheable y de alto volumen de lectura."""

    @abc.abstractmethod
    def get(self, key: str, default: str | None = None) -> str | None:
        """Valor de configuración de plataforma."""

    @abc.abstractmethod
    def get_tenant_config(self, tenant_id: TenantId) -> Mapping[str, Any]:
        """Configuración completa del tenant.

        Incluye al menos `thresholds`, `decision_issuer`, `retention` y
        `jurisdiction`. Lanza `ConfigurationError` si el tenant no existe.
        """

    @abc.abstractmethod
    def get_thresholds(self, tenant_id: TenantId) -> Mapping[str, float]:
        """Umbrales del motor de decisión para el tenant."""

    @abc.abstractmethod
    def get_decision_issuer(self, tenant_id: TenantId) -> DecisionIssuer:
        """Quién emite el veredicto para ese tenant.

        En Bolivia debe ser `SIGNALS_ONLY`: el art. 32(II) del Instructivo UIF
        prohíbe delegar en terceros la Debida Diligencia del cliente.
        """

    @abc.abstractmethod
    def is_tenant_active(self, tenant_id: TenantId) -> bool:
        """`True` si el tenant existe y no está suspendido."""


class AuthorizationProvider(abc.ABC):
    """Autorización **en el núcleo**, no en el gateway.

    GCP API Gateway solo admite autenticación declarativa (API keys, JWT,
    cuentas de servicio): no ejecuta código arbitrario por petición. Mantener
    la autorización aquí es lo que hace portable el diseño; además, el caché
    de authorizer de API Gateway se sustituye por caché en proceso con TTL.
    """

    @abc.abstractmethod
    def authorize(self, principal: str, tenant_id: TenantId, action: str) -> bool:
        """`True` si el principal puede ejecutar la acción sobre ese tenant."""

    @abc.abstractmethod
    def assert_authorized(self, principal: str, tenant_id: TenantId, action: str) -> None:
        """Como `authorize`, pero lanza `AuthorizationError` al denegar."""


__all__ = ["AuthorizationProvider", "ConfigProvider"]
