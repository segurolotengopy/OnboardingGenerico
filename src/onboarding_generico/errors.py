"""Jerarquía de errores del dominio.

Cada error lleva un **código estable** (contrato con el requirente: no cambia
entre versiones) y una marca de **reintentabilidad**, que el orquestador usa
para decidir entre reintentar, activar el proveedor de reserva o abortar.

Regla: ningún mensaje de error puede contener PII. Los detalles se limitan a
identificadores técnicos y nombres de campo, nunca a sus valores.
"""

from __future__ import annotations

from typing import Any, Mapping


class OnboardingError(Exception):
    """Raíz de todos los errores del middleware."""

    code: str = "OG_INTERNAL"
    retryable: bool = False
    http_status: int = 500

    def __init__(self, message: str, /, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = dict(details)

    def to_dict(self) -> dict[str, Any]:
        """Representación serializable, apta para respuesta de API y para log."""
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }

    def __repr__(self) -> str:  # pragma: no cover - ayuda de depuración
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


# --------------------------------------------------------------------------
# Configuración y arranque
# --------------------------------------------------------------------------


class ConfigurationError(OnboardingError):
    """Configuración ausente, contradictoria o fuera de rango."""

    code = "OG_CONFIGURATION"
    retryable = False


class MissingDependencyError(OnboardingError):
    """Falta un SDK opcional (boto3, google-cloud-*, onnxruntime, cv2...).

    Se lanza desde los imports diferidos de los adaptadores para que el error
    indique exactamente qué extra instalar en vez de un `ModuleNotFoundError`
    genérico a nivel de módulo.
    """

    code = "OG_MISSING_DEPENDENCY"
    retryable = False

    def __init__(self, package: str, extra: str) -> None:
        super().__init__(
            f"El paquete '{package}' no está instalado. "
            f"Instale el extra correspondiente: pip install onboarding-generico[{extra}]",
            package=package,
            extra=extra,
        )


# --------------------------------------------------------------------------
# Validación de entrada y de especificaciones
# --------------------------------------------------------------------------


class ValidationError(OnboardingError):
    """Entrada estructuralmente inválida."""

    code = "OG_VALIDATION"
    retryable = False
    http_status = 400


class SpecValidationError(ValidationError):
    """La especificación de flujo no supera una de las comprobaciones V1..V7."""

    code = "OG_SPEC_INVALID"
    http_status = 422

    def __init__(self, message: str, /, *, check: str = "V1", path: str = "") -> None:
        super().__init__(message, check=check, path=path)


class NoApplicableFlowSpecError(OnboardingError):
    """Ninguna especificación resuelve la clave (tenant, país, documento, tier)."""

    code = "OG_NO_APPLICABLE_FLOW_SPEC"
    retryable = False
    http_status = 422


class AmbiguousFlowSpecError(OnboardingError):
    """Dos especificaciones empatan en especificidad y prioridad."""

    code = "OG_AMBIGUOUS_FLOW_SPEC"
    retryable = False
    http_status = 422


class CapabilityNotProvisionedError(OnboardingError):
    """El tenant no tiene proveedor activo para alguna capacidad de la spec."""

    code = "OG_CAPABILITY_NOT_PROVISIONED"
    retryable = False
    http_status = 422


# --------------------------------------------------------------------------
# Dominio
# --------------------------------------------------------------------------


class DomainError(OnboardingError):
    """Violación de una invariante del agregado."""

    code = "OG_DOMAIN"
    retryable = False
    http_status = 409


class InvalidStateTransitionError(DomainError):
    """Transición no permitida por la máquina de estados."""

    code = "OG_INVALID_TRANSITION"

    def __init__(self, current: str, target: str) -> None:
        super().__init__(
            f"Transición no permitida: {current} -> {target}",
            current_state=current,
            target_state=target,
        )


class SessionNotFoundError(OnboardingError):
    """No existe la sesión dentro del alcance del tenant solicitado."""

    code = "OG_SESSION_NOT_FOUND"
    retryable = False
    http_status = 404


class ConcurrencyError(OnboardingError):
    """Falló el bloqueo optimista: otro escritor avanzó la versión."""

    code = "OG_CONCURRENCY"
    retryable = True
    http_status = 409


class LockAcquisitionError(OnboardingError):
    """No se pudo adquirir el mutex distribuido."""

    code = "OG_LOCK_UNAVAILABLE"
    retryable = True
    http_status = 423


class MrzParseError(ValidationError):
    """La MRZ no tiene la geometría esperada o contiene caracteres inválidos."""

    code = "OG_MRZ_PARSE"


class MrzCheckDigitError(ValidationError):
    """Uno o más dígitos de control 7-3-1 no cuadran."""

    code = "OG_MRZ_CHECK_DIGIT"

    def __init__(self, message: str, /, *, failures: Mapping[str, str] | None = None) -> None:
        super().__init__(message, failures=dict(failures or {}))


# --------------------------------------------------------------------------
# Criptografía y aislamiento
# --------------------------------------------------------------------------


class CryptoError(OnboardingError):
    """Error genérico de la capa criptográfica."""

    code = "OG_CRYPTO"
    retryable = False


class DecryptionError(CryptoError):
    """Fallo de descifrado o de verificación de integridad.

    Es el resultado esperado cuando el `tenant_id` usado como Associated Data
    no coincide con el del registro: un error de alcance produce un fallo, no
    una fuga de datos.
    """

    code = "OG_DECRYPTION_FAILED"


class KeyDestroyedError(CryptoError):
    """El material de clave del tenant fue destruido (crypto-shredding)."""

    code = "OG_KEY_DESTROYED"


class TenantIsolationError(OnboardingError):
    """Se detectó un acceso cruzado entre tenants antes de tocar el almacén."""

    code = "OG_TENANT_ISOLATION"
    retryable = False
    http_status = 403


class AuthorizationError(OnboardingError):
    """El principal no está autorizado para la operación sobre el tenant."""

    code = "OG_UNAUTHORIZED"
    retryable = False
    http_status = 403


class AuditChainError(DomainError):
    """La cadena de hash del log de auditoría no es consistente."""

    code = "OG_AUDIT_CHAIN"


# --------------------------------------------------------------------------
# Proveedores
# --------------------------------------------------------------------------


class ProviderError(OnboardingError):
    """Error al invocar a un proveedor externo."""

    code = "OG_PROVIDER"
    retryable = False
    http_status = 502


class ProviderUnavailableError(ProviderError):
    """El proveedor no responde. Activa la cadena de reserva."""

    code = "OG_PROVIDER_UNAVAILABLE"
    retryable = True


class ProviderThrottledError(ProviderError):
    """El proveedor aplicó limitación de tasa."""

    code = "OG_PROVIDER_THROTTLED"
    retryable = True


class ProviderContractViolationError(ProviderError):
    """La respuesta del proveedor no cumple el esquema de salida declarado."""

    code = "OG_PROVIDER_CONTRACT"
    retryable = False


class InconclusiveResultError(ProviderError):
    """El proveedor respondió con confianza insuficiente para decidir."""

    code = "OG_INCONCLUSIVE"
    retryable = False


#: Errores que, por defecto, activan la cadena de proveedores de reserva.
FALLBACK_TRIGGERS: frozenset[str] = frozenset(
    {
        ProviderUnavailableError.code,
        ProviderThrottledError.code,
        InconclusiveResultError.code,
        ProviderContractViolationError.code,
    }
)


class ObjectNotFoundError(OnboardingError):
    """El objeto referenciado no existe en el almacén."""

    code = "OG_OBJECT_NOT_FOUND"
    retryable = False
    http_status = 404


class IntegrityError(OnboardingError):
    """El sha256 declarado no coincide con el contenido almacenado (I6)."""

    code = "OG_INTEGRITY"
    retryable = False


__all__ = [
    "OnboardingError",
    "ConfigurationError",
    "MissingDependencyError",
    "ValidationError",
    "SpecValidationError",
    "NoApplicableFlowSpecError",
    "AmbiguousFlowSpecError",
    "CapabilityNotProvisionedError",
    "DomainError",
    "InvalidStateTransitionError",
    "SessionNotFoundError",
    "ConcurrencyError",
    "LockAcquisitionError",
    "MrzParseError",
    "MrzCheckDigitError",
    "CryptoError",
    "DecryptionError",
    "KeyDestroyedError",
    "TenantIsolationError",
    "AuthorizationError",
    "AuditChainError",
    "ProviderError",
    "ProviderUnavailableError",
    "ProviderThrottledError",
    "ProviderContractViolationError",
    "InconclusiveResultError",
    "ObjectNotFoundError",
    "IntegrityError",
    "FALLBACK_TRIGGERS",
]
