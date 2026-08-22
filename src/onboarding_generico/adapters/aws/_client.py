"""Fábrica de clientes de AWS con import diferido.

`boto3` se importa **dentro** de la función, nunca a nivel de módulo: así
`import onboarding_generico.adapters.aws` funciona sin el extra instalado y el
error, cuando llega, dice exactamente qué instalar.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ...errors import MissingDependencyError

EXTRA: str = "aws"


def require_boto3() -> Any:
    """Importa `boto3` o lanza `MissingDependencyError` con instrucción precisa."""
    try:
        import boto3  # import diferido a propósito: ver regla 3 de CLAUDE.md
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise MissingDependencyError("boto3", EXTRA) from exc
    return boto3


@lru_cache(maxsize=32)
def client(service: str, region: str) -> Any:
    """Cliente cacheado por (servicio, región).

    El caché importa: crear un cliente de boto3 por invocación de Lambda
    añade decenas de milisegundos de arranque en frío innecesarios.
    """
    return require_boto3().client(service, region_name=region)


@lru_cache(maxsize=8)
def resource(service: str, region: str) -> Any:
    """Recurso de alto nivel cacheado (usado por DynamoDB `Table`)."""
    return require_boto3().resource(service, region_name=region)


__all__ = ["EXTRA", "client", "require_boto3", "resource"]
