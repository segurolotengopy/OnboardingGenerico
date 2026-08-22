"""Log estructurado en JSON con redacción de PII y contexto de correlación.

Reglas que este módulo hace cumplir por construcción:

1. **Nunca se emite PII en claro.** Existe una lista de claves sensibles
   (`PII_KEYS`) y una lista de fragmentos (`PII_KEY_FRAGMENTS`); cualquier
   clave que coincida se sustituye por un marcador que conserva un hash
   truncado, suficiente para correlacionar sin revelar el valor.
2. **El contexto de correlación viaja aparte del mensaje.** `correlation_id`,
   `tenant_id` y `session_id` se propagan con `contextvars`, de modo que un
   caso de uso no tiene que pasarlos por parámetro a cada log.
3. **La salida es una sola línea JSON**, que es lo que consumen CloudWatch
   Logs Insights y Cloud Logging sin configuración adicional.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import sys
import uuid
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

#: Claves cuyo valor jamás se escribe en un log.
PII_KEYS: frozenset[str] = frozenset(
    {
        "first_name",
        "last_name",
        "given_names",
        "surname",
        "full_name",
        "name",
        "id_number",
        "document_number",
        "personal_number",
        "curp",
        "rfc",
        "ci",
        "birth_date",
        "date_of_birth",
        "expiry_date",
        "address",
        "email",
        "phone",
        "phone_number",
        "mrz",
        "mrz_lines",
        "selfie",
        "face_embedding",
        "embedding",
        "portrait",
        "raw_text",
        "blocks",
        "authorization",
        "password",
        "secret",
        "token",
        "task_token",
        "api_key",
        "access_key",
        "signature",
    }
)

#: Fragmentos que, contenidos en una clave, la marcan como sensible.
PII_KEY_FRAGMENTS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "credential",
    "authorization",
    "biometric",
    "fingerprint",
    "_pii",
)

REDACTED: str = "[REDACTED]"

_MAX_DEPTH = 6
_MAX_SEQUENCE_ITEMS = 20


@dataclass(frozen=True, slots=True)
class CorrelationContext:
    """Identificadores de correlación adjuntos a todo registro de log."""

    correlation_id: str
    tenant_id: str | None = None
    session_id: str | None = None
    step_id: str | None = None

    def as_dict(self) -> dict[str, str]:
        data = {"correlation_id": self.correlation_id}
        if self.tenant_id:
            data["tenant_id"] = self.tenant_id
        if self.session_id:
            data["session_id"] = self.session_id
        if self.step_id:
            data["step_id"] = self.step_id
        return data


#: Contexto por defecto cuando nadie abrió un `correlation_scope`. Es una
#: instancia congelada y compartida: `CorrelationContext` es un dataclass
#: `frozen=True`, así que no hay estado mutable compartido entre corrutinas.
_UNBOUND_CONTEXT: CorrelationContext = CorrelationContext(correlation_id="unbound")

_context: contextvars.ContextVar[CorrelationContext] = contextvars.ContextVar(
    "og_correlation_context",
    default=_UNBOUND_CONTEXT,
)


def current_context() -> CorrelationContext:
    """Devuelve el contexto de correlación vigente."""
    return _context.get()


def new_correlation_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def correlation_scope(
    *,
    correlation_id: str | None = None,
    tenant_id: str | None = None,
    session_id: str | None = None,
    step_id: str | None = None,
) -> Iterator[CorrelationContext]:
    """Instala un contexto de correlación durante el bloque.

    Los campos no indicados se heredan del contexto padre, lo que permite
    anidar un `step_id` dentro del alcance de una sesión sin repetir el resto.
    """
    parent = _context.get()
    ctx = CorrelationContext(
        correlation_id=correlation_id or parent.correlation_id or new_correlation_id(),
        tenant_id=tenant_id if tenant_id is not None else parent.tenant_id,
        session_id=session_id if session_id is not None else parent.session_id,
        step_id=step_id if step_id is not None else parent.step_id,
    )
    token = _context.set(ctx)
    try:
        yield ctx
    finally:
        _context.reset(token)


def _fingerprint(value: Any) -> str:
    """Hash truncado de un valor sensible, para correlacionar sin revelar."""
    digest = hashlib.sha256(repr(value).encode("utf-8")).hexdigest()
    return f"{REDACTED}:sha256:{digest[:12]}"


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in PII_KEYS:
        return True
    return any(fragment in lowered for fragment in PII_KEY_FRAGMENTS)


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Devuelve una copia de `value` con todas las claves sensibles redactadas."""
    if _depth > _MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            if is_sensitive_key(key):
                result[key] = _fingerprint(raw_value)
            else:
                result[key] = redact(raw_value, _depth=_depth + 1)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)[:_MAX_SEQUENCE_ITEMS]
        redacted = [redact(item, _depth=_depth + 1) for item in items]
        if len(value) > _MAX_SEQUENCE_ITEMS:
            redacted.append(f"[+{len(value) - _MAX_SEQUENCE_ITEMS} more]")
        return redacted
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class JsonFormatter(logging.Formatter):
    """Formateador de una línea JSON por registro, con redacción aplicada."""

    def __init__(
        self, *, service_name: str = "onboarding-generico", redact_pii: bool = True
    ) -> None:
        super().__init__()
        self.service_name = service_name
        self.redact_pii = redact_pii

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "service": self.service_name,
            "message": record.getMessage(),
        }
        payload.update(current_context().as_dict())

        extra = getattr(record, "og_fields", None)
        if isinstance(extra, Mapping) and extra:
            payload["fields"] = redact(extra) if self.redact_pii else dict(extra)

        if record.exc_info:
            exc_type = record.exc_info[0]
            payload["error_type"] = exc_type.__name__ if exc_type else "Unknown"
            payload["error_message"] = str(record.exc_info[1])

        return json.dumps(payload, ensure_ascii=False, sort_keys=False, default=str)


class StructuredLogger:
    """Fachada delgada sobre `logging` con firma `(mensaje, **campos)`."""

    __slots__ = ("_logger", "_redact")

    def __init__(self, logger: logging.Logger, *, redact_pii: bool = True) -> None:
        self._logger = logger
        self._redact = redact_pii

    def _emit(self, level: int, message: str, fields: MutableMapping[str, Any]) -> None:
        if not self._logger.isEnabledFor(level):
            return
        self._logger.log(level, message, extra={"og_fields": dict(fields)})

    def debug(self, message: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, message, fields)

    def info(self, message: str, **fields: Any) -> None:
        self._emit(logging.INFO, message, fields)

    def warning(self, message: str, **fields: Any) -> None:
        self._emit(logging.WARNING, message, fields)

    def error(self, message: str, **fields: Any) -> None:
        self._emit(logging.ERROR, message, fields)

    def exception(self, message: str, **fields: Any) -> None:
        if not self._logger.isEnabledFor(logging.ERROR):
            return
        self._logger.error(message, exc_info=True, extra={"og_fields": dict(fields)})


_configured = False


def configure_logging(
    *,
    level: str = "INFO",
    service_name: str = "onboarding-generico",
    redact_pii: bool = True,
    stream: Any | None = None,
) -> None:
    """Instala el formateador JSON en el logger raíz del paquete (idempotente)."""
    global _configured
    root = logging.getLogger("onboarding_generico")
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter(service_name=service_name, redact_pii=redact_pii))
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    _configured = True


def get_logger(name: str, *, redact_pii: bool = True) -> StructuredLogger:
    """Obtiene un logger estructurado bajo el espacio de nombres del paquete."""
    if not _configured:
        configure_logging()
    full_name = name if name.startswith("onboarding_generico") else f"onboarding_generico.{name}"
    return StructuredLogger(logging.getLogger(full_name), redact_pii=redact_pii)


__all__ = [
    "PII_KEYS",
    "PII_KEY_FRAGMENTS",
    "REDACTED",
    "CorrelationContext",
    "JsonFormatter",
    "StructuredLogger",
    "configure_logging",
    "correlation_scope",
    "current_context",
    "get_logger",
    "is_sensitive_key",
    "new_correlation_id",
    "redact",
]
