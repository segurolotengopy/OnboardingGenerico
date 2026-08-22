"""Configuración del proceso, leída de variables de entorno.

Principios:

- **Valores por defecto seguros**: el proveedor de nube por defecto es
  ``inmemory`` (nada sale del proceso), la redacción de PII está activa y el
  emisor del veredicto por defecto es ``SIGNALS_ONLY``, que es el único
  compatible con todas las jurisdicciones cubiertas.
- **Validación temprana**: un valor fuera de rango falla al arrancar, no en la
  primera petición.
- `ConfigPort` y `SecretsPort` están separados a propósito (ver brecha 9 de la
  referencia de paridad GCP: en GCP todo iría a Secret Manager, con un tope de
  600 lecturas/min por proyecto, inadecuado como almacén de configuración).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Final, Mapping

from .errors import ConfigurationError

ENV_PREFIX: Final[str] = "OG_"

#: Proveedores de nube soportados por el composition root.
SUPPORTED_CLOUD_PROVIDERS: Final[frozenset[str]] = frozenset({"inmemory", "aws", "gcp"})

#: Emisores del veredicto (ver doc 04 §4.3). ``MIDDLEWARE`` está prohibido en BO.
SUPPORTED_DECISION_ISSUERS: Final[frozenset[str]] = frozenset(
    {"MIDDLEWARE", "SIGNALS_ONLY", "REQUESTER_CONFIRMS"}
)


def _get(env: Mapping[str, str], name: str, default: str) -> str:
    return env.get(ENV_PREFIX + name, default).strip()


def _get_bool(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _get(env, name, "true" if default else "false").lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ConfigurationError(
        f"{ENV_PREFIX}{name} debe ser un booleano", variable=ENV_PREFIX + name, value=raw
    )


def _get_int(env: Mapping[str, str], name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = _get(env, name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"{ENV_PREFIX}{name} debe ser un entero", variable=ENV_PREFIX + name, value=raw
        ) from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(
            f"{ENV_PREFIX}{name} fuera de rango [{minimum}, {maximum}]",
            variable=ENV_PREFIX + name,
            value=value,
        )
    return value


def _get_float(
    env: Mapping[str, str], name: str, default: float, *, minimum: float, maximum: float
) -> float:
    raw = _get(env, name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"{ENV_PREFIX}{name} debe ser un número", variable=ENV_PREFIX + name, value=raw
        ) from exc
    if not minimum <= value <= maximum:
        raise ConfigurationError(
            f"{ENV_PREFIX}{name} fuera de rango [{minimum}, {maximum}]",
            variable=ENV_PREFIX + name,
            value=value,
        )
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    """Configuración inmutable del proceso."""

    environment: str = "dev"
    cloud_provider: str = "inmemory"
    region: str = "us-east-1"
    service_name: str = "onboarding-generico"
    #: Proyecto de GCP. Vacío con `cloud_provider` distinto de `gcp`.
    gcp_project: str = ""

    # Observabilidad
    log_level: str = "INFO"
    redact_pii: bool = True
    telemetry_enabled: bool = True

    # Almacenamiento de objetos
    artifact_bucket: str = "og-dev-artifacts"
    presign_ttl_seconds: int = 900

    # Sesión
    session_ttl_seconds: int = 3600
    capture_window_seconds: int = 1800
    max_artifact_bytes: int = 12_000_000

    # Criptografía
    key_cache_ttl_seconds: int = 300
    key_cache_max_entries: int = 512
    kms_key_alias: str = "alias/og-dev-tenant"

    # Decisión
    default_decision_issuer: str = "SIGNALS_ONLY"
    face_match_min_similarity: float = 0.82
    face_match_grey_band_low: float = 0.74
    liveness_min_score: float = 0.90
    ocr_min_field_confidence: float = 0.85

    # Composición
    flow_spec_namespace: str = "GLOBAL"

    #: Nombres de variable efectivamente leídos, útil para diagnósticos.
    read_variables: tuple[str, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        if self.cloud_provider not in SUPPORTED_CLOUD_PROVIDERS:
            raise ConfigurationError(
                "Proveedor de nube no soportado",
                variable=ENV_PREFIX + "CLOUD_PROVIDER",
                value=self.cloud_provider,
                supported=sorted(SUPPORTED_CLOUD_PROVIDERS),
            )
        if self.default_decision_issuer not in SUPPORTED_DECISION_ISSUERS:
            raise ConfigurationError(
                "Emisor del veredicto no soportado",
                variable=ENV_PREFIX + "DEFAULT_DECISION_ISSUER",
                value=self.default_decision_issuer,
            )
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ConfigurationError(
                "Nivel de log no soportado",
                variable=ENV_PREFIX + "LOG_LEVEL",
                value=self.log_level,
            )
        if self.cloud_provider == "gcp" and not self.gcp_project:
            raise ConfigurationError(
                "OG_GCP_PROJECT es obligatorio con OG_CLOUD_PROVIDER=gcp",
                variable=ENV_PREFIX + "GCP_PROJECT",
            )
        if self.face_match_grey_band_low > self.face_match_min_similarity:
            raise ConfigurationError(
                "El piso de la banda gris no puede superar el umbral de similitud",
                grey_band_low=self.face_match_grey_band_low,
                min_similarity=self.face_match_min_similarity,
            )

    @property
    def is_production(self) -> bool:
        return self.environment in {"prod", "production"}

    def resource_name(self, component: str) -> str:
        """Nomenclatura obligatoria del proyecto: ``og-{env}-{componente}``."""
        return f"og-{self.environment}-{component}"


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """Construye `Settings` desde el entorno, validando cada valor.

    Se pasa `env` explícitamente en las pruebas para no depender de
    `os.environ` del proceso.
    """
    source: Mapping[str, str] = os.environ if env is None else env
    read = tuple(sorted(k for k in source if k.startswith(ENV_PREFIX)))

    settings = Settings(
        environment=_get(source, "ENVIRONMENT", "dev"),
        cloud_provider=_get(source, "CLOUD_PROVIDER", "inmemory").lower(),
        region=_get(source, "REGION", "us-east-1"),
        service_name=_get(source, "SERVICE_NAME", "onboarding-generico"),
        gcp_project=_get(source, "GCP_PROJECT", ""),
        log_level=_get(source, "LOG_LEVEL", "INFO").upper(),
        redact_pii=_get_bool(source, "REDACT_PII", True),
        telemetry_enabled=_get_bool(source, "TELEMETRY_ENABLED", True),
        artifact_bucket=_get(source, "ARTIFACT_BUCKET", "og-dev-artifacts"),
        presign_ttl_seconds=_get_int(source, "PRESIGN_TTL_SECONDS", 900, minimum=60, maximum=43_200),
        session_ttl_seconds=_get_int(source, "SESSION_TTL_SECONDS", 3600, minimum=300, maximum=604_800),
        capture_window_seconds=_get_int(
            source, "CAPTURE_WINDOW_SECONDS", 1800, minimum=120, maximum=604_800
        ),
        max_artifact_bytes=_get_int(
            source, "MAX_ARTIFACT_BYTES", 12_000_000, minimum=1_000, maximum=50_000_000
        ),
        key_cache_ttl_seconds=_get_int(source, "KEY_CACHE_TTL_SECONDS", 300, minimum=1, maximum=3_600),
        key_cache_max_entries=_get_int(source, "KEY_CACHE_MAX_ENTRIES", 512, minimum=1, maximum=100_000),
        kms_key_alias=_get(source, "KMS_KEY_ALIAS", "alias/og-dev-tenant"),
        default_decision_issuer=_get(source, "DEFAULT_DECISION_ISSUER", "SIGNALS_ONLY").upper(),
        face_match_min_similarity=_get_float(
            source, "FACE_MATCH_MIN_SIMILARITY", 0.82, minimum=0.0, maximum=1.0
        ),
        face_match_grey_band_low=_get_float(
            source, "FACE_MATCH_GREY_BAND_LOW", 0.74, minimum=0.0, maximum=1.0
        ),
        liveness_min_score=_get_float(source, "LIVENESS_MIN_SCORE", 0.90, minimum=0.0, maximum=1.0),
        ocr_min_field_confidence=_get_float(
            source, "OCR_MIN_FIELD_CONFIDENCE", 0.85, minimum=0.0, maximum=1.0
        ),
        flow_spec_namespace=_get(source, "FLOW_SPEC_NAMESPACE", "GLOBAL"),
        read_variables=read,
    )
    return settings


__all__ = [
    "Settings",
    "load_settings",
    "ENV_PREFIX",
    "SUPPORTED_CLOUD_PROVIDERS",
    "SUPPORTED_DECISION_ISSUERS",
]
