"""Pruebas de configuración, observabilidad y jerarquía de errores."""

from __future__ import annotations

import dataclasses
import io
import json
import logging
import threading

import pytest

from onboarding_generico.config import (
    SUPPORTED_CLOUD_PROVIDERS,
    Settings,
    load_settings,
)
from onboarding_generico.errors import (
    FALLBACK_TRIGGERS,
    ConcurrencyError,
    MissingDependencyError,
    OnboardingError,
    ProviderThrottledError,
    ProviderUnavailableError,
    ValidationError,
)
from onboarding_generico.observability import (
    PII_KEYS,
    REDACTED,
    JsonFormatter,
    configure_logging,
    correlation_scope,
    current_context,
    get_logger,
    is_sensitive_key,
    new_correlation_id,
    redact,
)

# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------


def test_defaults_are_safe() -> None:
    """Sin variables de entorno: nada sale del proceso y la PII se redacta."""
    settings = load_settings({})
    assert settings.cloud_provider == "inmemory"
    assert settings.redact_pii is True
    assert settings.default_decision_issuer == "SIGNALS_ONLY"
    assert settings.is_production is False


def test_reads_environment() -> None:
    settings = load_settings(
        {
            "OG_ENVIRONMENT": "prod",
            "OG_CLOUD_PROVIDER": "aws",
            "OG_REGION": "sa-east-1",
            "OG_LIVENESS_MIN_SCORE": "0.95",
            "OG_REDACT_PII": "false",
        }
    )
    assert settings.environment == "prod"
    assert settings.cloud_provider == "aws"
    assert settings.liveness_min_score == pytest.approx(0.95)
    assert settings.redact_pii is False
    assert settings.is_production is True


def test_resource_naming_convention() -> None:
    settings = load_settings({"OG_ENVIRONMENT": "stg"})
    assert settings.resource_name("core") == "og-stg-core"


@pytest.mark.parametrize(
    "env",
    [
        {"OG_CLOUD_PROVIDER": "azure"},
        {"OG_LOG_LEVEL": "VERBOSE"},
        {"OG_DEFAULT_DECISION_ISSUER": "ROBOT"},
        {"OG_PRESIGN_TTL_SECONDS": "1"},
        {"OG_PRESIGN_TTL_SECONDS": "no-numerico"},
        {"OG_LIVENESS_MIN_SCORE": "1.5"},
        {"OG_REDACT_PII": "quizas"},
        {"OG_FACE_MATCH_MIN_SIMILARITY": "0.60", "OG_FACE_MATCH_GREY_BAND_LOW": "0.80"},
        {"OG_CLOUD_PROVIDER": "gcp"},
    ],
)
def test_invalid_configuration_fails_at_startup(env: dict[str, str]) -> None:
    with pytest.raises(OnboardingError) as excinfo:
        load_settings(env)
    assert excinfo.value.code == "OG_CONFIGURATION"


def test_gcp_requires_project() -> None:
    settings = load_settings({"OG_CLOUD_PROVIDER": "gcp", "OG_GCP_PROJECT": "og-prod"})
    assert settings.gcp_project == "og-prod"


def test_supported_providers_are_the_three_expected() -> None:
    assert {"inmemory", "aws", "gcp"} == SUPPORTED_CLOUD_PROVIDERS


def test_settings_are_immutable() -> None:
    settings = Settings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.environment = "otro"  # type: ignore[misc]


# --------------------------------------------------------------------------
# Errores
# --------------------------------------------------------------------------


def test_error_codes_are_stable_and_serializable() -> None:
    error = ValidationError("campo inválido", field="slot")
    assert error.code == "OG_VALIDATION"
    assert error.retryable is False
    assert error.http_status == 400
    assert error.to_dict() == {
        "code": "OG_VALIDATION",
        "message": "campo inválido",
        "retryable": False,
        "details": {"field": "slot"},
    }


def test_retryable_errors_are_marked() -> None:
    assert ProviderUnavailableError("x").retryable is True
    assert ProviderThrottledError("x").retryable is True
    assert ConcurrencyError("x").retryable is True
    assert ValidationError("x").retryable is False


def test_fallback_triggers_cover_the_expected_codes() -> None:
    assert ProviderUnavailableError.code in FALLBACK_TRIGGERS
    assert ProviderThrottledError.code in FALLBACK_TRIGGERS
    assert ValidationError.code not in FALLBACK_TRIGGERS


def test_missing_dependency_names_the_extra() -> None:
    error = MissingDependencyError("boto3", "aws")
    assert "onboarding-generico[aws]" in error.message
    assert error.details["package"] == "boto3"


def test_every_error_inherits_from_the_root() -> None:
    for error_type in (ValidationError, ConcurrencyError, ProviderUnavailableError):
        assert issubclass(error_type, OnboardingError)


# --------------------------------------------------------------------------
# Observabilidad
# --------------------------------------------------------------------------


def test_pii_keys_include_the_obvious_ones() -> None:
    for key in ("first_name", "id_number", "birth_date", "mrz", "face_embedding"):
        assert key in PII_KEYS
        assert is_sensitive_key(key) is True


def test_sensitive_key_fragments() -> None:
    assert is_sensitive_key("client_secret") is True
    assert is_sensitive_key("X-Auth-Token") is True
    assert is_sensitive_key("biometric_template") is True
    assert is_sensitive_key("country") is False


def test_redact_replaces_values_with_a_stable_fingerprint() -> None:
    redacted = redact({"id_number": "D23145890", "country": "MX"})
    assert redacted["country"] == "MX"
    assert str(redacted["id_number"]).startswith(REDACTED)
    assert "D23145890" not in str(redacted)
    assert redact({"id_number": "D23145890"})["id_number"] == redacted["id_number"]


def test_redact_is_recursive_and_bounded() -> None:
    nested = {"outer": {"inner": {"first_name": "ANNA"}}, "items": list(range(50))}
    redacted = redact(nested)
    assert "ANNA" not in str(redacted)
    assert len(redacted["items"]) == 21  # 20 elementos + marcador de truncado
    assert "more" in str(redacted["items"][-1])


def test_deeply_nested_structures_are_truncated() -> None:
    payload: dict[str, object] = {"a": {}}
    cursor = payload["a"]
    for _ in range(12):
        nxt: dict[str, object] = {}
        cursor["a"] = nxt  # type: ignore[index]
        cursor = nxt
    assert "TRUNCATED" in str(redact(payload))


def test_logger_emits_one_json_line_with_context() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", service_name="og-test", stream=stream)
    logger = get_logger("prueba")
    with correlation_scope(correlation_id="corr-1", tenant_id="acme", session_id="s1"):
        logger.info("paso completado", step_id="ocr", id_number="D23145890")

    lines = [line for line in stream.getvalue().splitlines() if line]
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["level"] == "INFO"
    assert record["service"] == "og-test"
    assert record["correlation_id"] == "corr-1"
    assert record["tenant_id"] == "acme"
    assert record["session_id"] == "s1"
    assert record["fields"]["step_id"] == "ocr"
    assert "D23145890" not in lines[0]


def test_logger_never_leaks_pii_even_in_the_message_fields() -> None:
    stream = io.StringIO()
    configure_logging(level="DEBUG", stream=stream)
    logger = get_logger("prueba")
    logger.warning(
        "extracción",
        claims={"first_name": "ANNA", "last_name": "ERIKSSON"},
        mrz_lines=["I<UTOD231458907"],
    )
    output = stream.getvalue()
    assert "ANNA" not in output
    assert "ERIKSSON" not in output
    assert "D231458907" not in output


def test_correlation_scope_inherits_and_restores() -> None:
    with correlation_scope(correlation_id="c1", tenant_id="acme"):
        assert current_context().tenant_id == "acme"
        with correlation_scope(step_id="ocr"):
            inner = current_context()
            assert inner.correlation_id == "c1"
            assert inner.tenant_id == "acme"
            assert inner.step_id == "ocr"
        assert current_context().step_id is None
    assert current_context().tenant_id is None


def test_correlation_context_is_thread_local() -> None:
    seen: list[str | None] = []

    def worker() -> None:
        seen.append(current_context().tenant_id)

    with correlation_scope(tenant_id="acme"):
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
    assert seen == [None]


def test_exception_logging_includes_type_without_traceback_pii() -> None:
    stream = io.StringIO()
    configure_logging(level="ERROR", stream=stream)
    logger = get_logger("prueba")
    try:
        raise ValidationError("campo inválido", field="slot")
    except ValidationError:
        logger.exception("fallo", step_id="ocr")
    record = json.loads(stream.getvalue().splitlines()[0])
    assert record["error_type"] == "ValidationError"
    assert record["fields"]["step_id"] == "ocr"


def test_new_correlation_id_is_unique() -> None:
    assert new_correlation_id() != new_correlation_id()


def test_formatter_can_disable_redaction_explicitly() -> None:
    """Solo para depuración local; nunca en producción."""
    formatter = JsonFormatter(redact_pii=False)
    record = logging.LogRecord("x", logging.INFO, "f", 1, "m", None, None)
    record.og_fields = {"id_number": "D23145890"}  # type: ignore[attr-defined]
    assert "D23145890" in formatter.format(record)
