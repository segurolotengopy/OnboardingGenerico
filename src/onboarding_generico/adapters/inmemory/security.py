"""Adaptadores en memoria de secretos, configuración y autorización.

La autorización vive aquí, en el núcleo del proceso, y no en el gateway: GCP
API Gateway no admite ejecución de código arbitrario por petición. Se
implementa con caché en proceso con TTL, que sustituye al caché de authorizer
de API Gateway (hasta 3.600 s) que se pierde al portar.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping
from typing import Any

from ...domain.enums import DecisionIssuer
from ...domain.value_objects import TenantId
from ...errors import AuthorizationError, ConfigurationError
from ...ports.config_port import AuthorizationProvider, ConfigProvider
from ...ports.secrets import SecretsProvider

#: Configuración por defecto de un tenant nuevo. Deliberadamente conservadora:
#: `SIGNALS_ONLY` es el único emisor compatible con todas las jurisdicciones.
DEFAULT_TENANT_CONFIG: dict[str, Any] = {
    "active": True,
    "jurisdiction": "MX",
    "decision_issuer": DecisionIssuer.SIGNALS_ONLY.value,
    "thresholds": {
        "face_match_min": 0.82,
        "face_match_grey_band_low": 0.74,
        "liveness_min": 0.90,
        "ocr_min_field_confidence": 0.85,
        "forgery_max_score": 0.30,
    },
    "retention": {"inherits_from": "jurisdiction", "min_years": 5},
}


class InMemorySecretsProvider(SecretsProvider):
    """Secretos en memoria. **Nunca** se sirve un valor por defecto silencioso."""

    __slots__ = ("_lock", "_secrets", "_versions")

    def __init__(self, secrets: Mapping[str, str] | None = None) -> None:
        self._secrets: dict[str, str] = dict(secrets or {})
        self._versions: dict[str, int] = dict.fromkeys(self._secrets, 1)
        self._lock = threading.Lock()

    def get_secret(self, name: str, *, version: str = "latest") -> str:
        with self._lock:
            if name not in self._secrets:
                raise ConfigurationError("el secreto no existe", secret_name=name)
            return self._secrets[name]

    def get_secret_json(self, name: str, *, version: str = "latest") -> Mapping[str, object]:
        raw = self.get_secret(name, version=version)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigurationError("el secreto no es JSON válido", secret_name=name) from exc
        if not isinstance(parsed, dict):
            raise ConfigurationError("el secreto JSON debe ser un objeto", secret_name=name)
        return parsed

    def rotate(self, name: str) -> str:
        """Emula la rotación. En GCP el rotador es código propio, no gestionado."""
        with self._lock:
            if name not in self._secrets:
                raise ConfigurationError("el secreto no existe", secret_name=name)
            self._versions[name] = self._versions.get(name, 1) + 1
            return str(self._versions[name])

    def set_secret(self, name: str, value: str) -> None:
        """Utilidad de prueba: inyecta un secreto ficticio."""
        with self._lock:
            self._secrets[name] = value
            self._versions.setdefault(name, 1)


class InMemoryConfigProvider(ConfigProvider):
    """Configuración de plataforma y por tenant."""

    __slots__ = ("_lock", "_platform", "_tenants")

    def __init__(
        self,
        platform: Mapping[str, str] | None = None,
        tenants: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
        self._platform: dict[str, str] = dict(platform or {})
        self._tenants: dict[str, dict[str, Any]] = {k: dict(v) for k, v in (tenants or {}).items()}
        self._lock = threading.RLock()

    def get(self, key: str, default: str | None = None) -> str | None:
        with self._lock:
            return self._platform.get(key, default)

    def get_tenant_config(self, tenant_id: TenantId) -> Mapping[str, Any]:
        with self._lock:
            config = self._tenants.get(tenant_id.value)
        if config is None:
            raise ConfigurationError("el tenant no está configurado", tenant_id=tenant_id.value)
        merged = dict(DEFAULT_TENANT_CONFIG)
        merged.update(config)
        return merged

    def get_thresholds(self, tenant_id: TenantId) -> Mapping[str, float]:
        config = self.get_tenant_config(tenant_id)
        thresholds = config.get("thresholds", {})
        return {str(k): float(v) for k, v in dict(thresholds).items()}

    def get_decision_issuer(self, tenant_id: TenantId) -> DecisionIssuer:
        config = self.get_tenant_config(tenant_id)
        issuer = DecisionIssuer(
            str(config.get("decision_issuer", DecisionIssuer.SIGNALS_ONLY.value))
        )
        # Regla de cumplimiento codificada, no una nota de manual: en Bolivia
        # el sujeto obligado no puede delegar la Debida Diligencia (art. 32(II)
        # del Instructivo UIF).
        if config.get("jurisdiction") == "BO" and issuer is DecisionIssuer.MIDDLEWARE:
            raise ConfigurationError(
                "un tenant con jurisdicción BO no admite 'MIDDLEWARE' como emisor del veredicto",
                tenant_id=tenant_id.value,
                jurisdiction="BO",
            )
        return issuer

    def is_tenant_active(self, tenant_id: TenantId) -> bool:
        with self._lock:
            config = self._tenants.get(tenant_id.value)
        return bool(config and config.get("active", True))

    def register_tenant(self, tenant_id: TenantId, config: Mapping[str, Any] | None = None) -> None:
        """Utilidad de aprovisionamiento para pruebas y desarrollo local."""
        with self._lock:
            merged = dict(DEFAULT_TENANT_CONFIG)
            merged.update(dict(config or {}))
            self._tenants[tenant_id.value] = merged


class InMemoryAuthorizationProvider(AuthorizationProvider):
    """Autorización en el núcleo, con concesiones explícitas por tenant."""

    __slots__ = ("_grants", "_lock")

    #: Acciones del contrato de API.
    ACTIONS: frozenset[str] = frozenset(
        {
            "session:create",
            "session:read",
            "session:submit_artifact",
            "session:decide",
            "review:read",
            "review:resolve",
            "tenant:purge",
            "flow:publish",
        }
    )

    def __init__(self, grants: Mapping[str, Mapping[str, Any]] | None = None) -> None:
        self._grants: dict[str, dict[str, set[str]]] = {}
        self._lock = threading.RLock()
        for principal, tenants in (grants or {}).items():
            for tenant, actions in tenants.items():
                self.grant(principal, TenantId(tenant), actions)

    def grant(self, principal: str, tenant_id: TenantId, actions: Any) -> None:
        """Concede acciones. `'*'` concede todas las del contrato."""
        resolved = set(self.ACTIONS) if actions == "*" else set(actions)
        unknown = resolved - self.ACTIONS
        if unknown:
            raise ConfigurationError("acciones desconocidas", actions=sorted(unknown))
        with self._lock:
            self._grants.setdefault(principal, {}).setdefault(tenant_id.value, set()).update(
                resolved
            )

    def revoke(self, principal: str, tenant_id: TenantId) -> None:
        with self._lock:
            self._grants.get(principal, {}).pop(tenant_id.value, None)

    def authorize(self, principal: str, tenant_id: TenantId, action: str) -> bool:
        with self._lock:
            return action in self._grants.get(principal, {}).get(tenant_id.value, set())

    def assert_authorized(self, principal: str, tenant_id: TenantId, action: str) -> None:
        if not self.authorize(principal, tenant_id, action):
            raise AuthorizationError(
                "el principal no está autorizado para esta acción sobre el tenant",
                principal=principal,
                tenant_id=tenant_id.value,
                action=action,
            )


__all__ = [
    "DEFAULT_TENANT_CONFIG",
    "InMemoryAuthorizationProvider",
    "InMemoryConfigProvider",
    "InMemorySecretsProvider",
]
