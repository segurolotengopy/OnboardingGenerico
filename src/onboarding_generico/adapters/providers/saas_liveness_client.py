"""Cliente de un proveedor SaaS de liveness con certificación iBeta PAD.

**Por qué existe este adaptador y no uno por nube.** GCP no tiene liveness
facial gestionado: Cloud Vision declara explícitamente que no soporta
reconocimiento facial individual, y no hay antispoofing, ni reto de vivacidad,
ni SDK de cliente. Si se usara Rekognition en AWS y un SaaS en GCP, el
`LivenessPort` acabaría con tres adaptadores y, peor, con **dos frontends
distintos**, porque la parte de cliente es un SDK de app. La recomendación es
usar **el mismo SaaS en ambas nubes** y eliminar la asimetría de raíz.

Requisitos que el proveedor debe acreditar (ISO/IEC 30107-3):

- Certificación **iBeta PAD Level 1 y Level 2**, con informe vigente.
- Métricas normativas declaradas: APCER, BPCER y, cuando aplique, RIAPAR.
- **Detección de inyección**, que es un vector distinto del ataque de
  presentación y que varias certificaciones no cubren.

**No se construye liveness propio con modelos abiertos** para un flujo KYC en
producción. `minivision-ai/Silent-Face-Anti-Spoofing` es Apache-2.0 pero su
modelo es de 2020, y usar PAD sin certificar en un proceso de debida
diligencia es riesgo regulatorio, no solo técnico.

Licencia: este cliente es código propio; el servicio se consume por contrato
comercial y su SDK de frontend tiene su propia licencia, que hay que revisar
por separado.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.value_objects import ObjectRef, TenantId
from ...errors import ProviderUnavailableError
from ...ports.liveness import LivenessPort, LivenessResult, LivenessSession
from ...ports.secrets import SecretsProvider

#: Nombre del secreto con la credencial del proveedor. **Nunca en el código.**
#: Es el identificador del secreto en el gestor de secretos, no su valor.
API_KEY_SECRET_NAME: str = "og/liveness/api-key"  # noqa: S105 - nombre del secreto, no la credencial

DEFAULT_TIMEOUT_SECONDS: float = 10.0


class SaasLivenessClient(LivenessPort):
    """Cliente HTTP del proveedor de liveness, idéntico en AWS y en GCP."""

    __slots__ = ("_base_url", "_secrets", "_settings", "_timeout")

    PROVIDER_ID = "saas_liveness"

    def __init__(
        self,
        settings: Settings,
        secrets: SecretsProvider | None = None,
        base_url: str = "",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings
        self._secrets = secrets
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds

    def _api_key(self) -> str:
        if self._secrets is None:
            raise ProviderUnavailableError(
                "no hay proveedor de secretos configurado para el cliente de liveness",
                provider_id=self.PROVIDER_ID,
            )
        return self._secrets.get_secret(API_KEY_SECRET_NAME)

    def _request(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Petición HTTPS con `urllib` de la stdlib.

        Se evita `requests` a propósito: es una dependencia más en la imagen
        de la función y esta es la única llamada HTTP saliente del proceso.
        """
        import json
        import urllib.error
        import urllib.request

        if not self._base_url:
            raise ProviderUnavailableError(
                "no hay URL base configurada para el proveedor de liveness",
                provider_id=self.PROVIDER_ID,
            )
        # La URL base viene de configuración, así que el esquema es entrada no
        # confiable: sin esta comprobación un `file://` convertiría `urlopen`
        # en una lectura del sistema de archivos de la función. Solo HTTPS: la
        # credencial del proveedor viaja en la cabecera Authorization.
        if not self._base_url.startswith("https://"):
            raise ProviderUnavailableError(
                "la URL base del proveedor de liveness debe usar HTTPS",
                provider_id=self.PROVIDER_ID,
            )
        payload = json.dumps(body or {}).encode("utf-8")
        request = urllib.request.Request(  # noqa: S310 - esquema validado como https arriba
            f"{self._base_url}{path}",
            data=payload if method != "GET" else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key()}",
                "User-Agent": f"onboarding-generico/{self._settings.environment}",
            },
        )
        try:
            # El esquema ya se validó como https más arriba.
            with urllib.request.urlopen(request, timeout=self._timeout) as response:  # noqa: S310
                parsed: dict[str, Any] = json.loads(response.read().decode("utf-8"))
                return parsed
        except urllib.error.HTTPError as exc:
            from ...errors import ProviderThrottledError

            if exc.code == 429:
                raise ProviderThrottledError(
                    "el proveedor de liveness aplicó limitación de tasa",
                    provider_id=self.PROVIDER_ID,
                ) from exc
            raise ProviderUnavailableError(
                "el proveedor de liveness devolvió un error HTTP",
                provider_id=self.PROVIDER_ID,
                status=exc.code,
            ) from exc
        except Exception as exc:
            raise ProviderUnavailableError(
                "el proveedor de liveness no respondió", provider_id=self.PROVIDER_ID
            ) from exc

    def create_session(self, tenant_id: TenantId, *, ttl_seconds: int = 300) -> LivenessSession:
        response = self._request(
            "POST",
            "/v1/liveness-sessions",
            {
                # No se envía ningún identificador del titular: el proveedor
                # solo necesita saber a qué contrato imputar la sesión.
                "tenant_reference": tenant_id.value,
                "ttl_seconds": ttl_seconds,
                "require_injection_detection": True,
            },
        )
        return LivenessSession(
            provider_session_id=str(response["session_id"]),
            client_token=str(response["client_token"]),
            expires_in_seconds=int(response.get("expires_in", ttl_seconds)),
            provider_id=self.PROVIDER_ID,
        )

    def get_result(
        self, tenant_id: TenantId, provider_session_id: str, *, threshold: float = 0.90
    ) -> LivenessResult:
        response = self._request("GET", f"/v1/liveness-sessions/{provider_session_id}")
        score = float(response.get("score", 0.0))
        injection = bool(response.get("injection_detected", False))
        audited: ObjectRef | None = None
        if response.get("audit_image"):
            raise NotImplementedError(
                "Falta decidir el circuito de la imagen auditada. El proveedor la devuelve por "
                "URL temporal; para cumplir la invariante I6 hay que descargarla, calcular su "
                "sha256 y depositarla en el almacén propio. Queda por decidir si esa copia entra "
                "en la clase de dato BIOMETRICO con su plazo de purga (lo correcto por "
                "minimización) o si se conserva más tiempo como evidencia de la decisión. Es una "
                "decisión del responsable del tratamiento."
            )
        return LivenessResult(
            score=score,
            threshold=threshold,
            passed=score >= threshold and not injection,
            injection_detected=injection,
            audited_image=audited,
            provider_id=self.PROVIDER_ID,
            pad_level=str(response.get("pad_level", "unknown")),
        )


__all__ = ["API_KEY_SECRET_NAME", "DEFAULT_TIMEOUT_SECONDS", "SaasLivenessClient"]
