"""Puerto de secretos.

Separado a propósito de `ConfigPort` (ver `config_port.py`): GCP no distingue
configuración de secretos y enviarlo todo a Secret Manager choca con su límite
de **600 lecturas/min por proyecto**, inadecuado para configuración de alto
volumen. Además, la rotación automática de credenciales **no es gestionada** en
GCP: solo hay notificaciones Pub/Sub y el rotador lo escribe el equipo.
"""

from __future__ import annotations

import abc
from collections.abc import Mapping


class SecretsProvider(abc.ABC):
    """Acceso de solo lectura a secretos, con caché en proceso en el adaptador."""

    @abc.abstractmethod
    def get_secret(self, name: str, *, version: str = "latest") -> str:
        """Valor del secreto. Lanza `ConfigurationError` si no existe."""

    @abc.abstractmethod
    def get_secret_json(self, name: str, *, version: str = "latest") -> Mapping[str, object]:
        """Secreto con estructura JSON, ya deserializado."""

    @abc.abstractmethod
    def rotate(self, name: str) -> str:
        """Solicita rotación y devuelve la nueva versión.

        En GCP el rotador es código propio: el servicio solo emite el aviso.
        """


__all__ = ["SecretsProvider"]
