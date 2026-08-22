"""Fábrica de clientes de GCP con import diferido.

Cada cliente vive en su propio paquete `google-cloud-*`, así que el import se
hace por servicio y el error indica el extra concreto.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from ...errors import MissingDependencyError

EXTRA: str = "gcp"


def require(module_path: str, package_name: str) -> Any:
    """Importa un módulo de GCP o lanza `MissingDependencyError`."""
    import importlib  # noqa: PLC0415

    try:
        return importlib.import_module(module_path)
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise MissingDependencyError(package_name, EXTRA) from exc


@lru_cache(maxsize=1)
def firestore_client(project: str, database: str = "(default)") -> Any:
    """Cliente de Firestore.

    Recordatorio de seguridad: **las bibliotecas de servidor ignoran por
    completo las Security Rules de Firestore**. El aislamiento por tenant lo
    aplica este código de forma explícita y lo respalda el cifrado con AAD.
    """
    module = require("google.cloud.firestore", "google-cloud-firestore")
    return module.Client(project=project, database=database)


@lru_cache(maxsize=1)
def storage_client(project: str) -> Any:
    module = require("google.cloud.storage", "google-cloud-storage")
    return module.Client(project=project)


@lru_cache(maxsize=1)
def secret_manager_client() -> Any:
    module = require("google.cloud.secretmanager", "google-cloud-secret-manager")
    return module.SecretManagerServiceClient()


@lru_cache(maxsize=1)
def kms_client() -> Any:
    module = require("google.cloud.kms", "google-cloud-kms")
    return module.KeyManagementServiceClient()


@lru_cache(maxsize=1)
def publisher_client(*, ordering: bool = True) -> Any:
    """Publicador de Pub/Sub con **ordering keys** activadas.

    Las ordering keys son la única forma de recuperar el orden que Firestore +
    Eventarc no garantiza.
    """
    module = require("google.cloud.pubsub_v1", "google-cloud-pubsub")
    options = module.types.PublisherOptions(enable_message_ordering=ordering)
    return module.PublisherClient(publisher_options=options)


@lru_cache(maxsize=1)
def workflows_executions_client() -> Any:
    module = require("google.cloud.workflows.executions_v1", "google-cloud-workflows")
    return module.ExecutionsClient()


@lru_cache(maxsize=1)
def documentai_client(location: str) -> Any:
    module = require("google.cloud.documentai", "google-cloud-documentai")
    return module.DocumentProcessorServiceClient(
        client_options={"api_endpoint": f"{location}-documentai.googleapis.com"}
    )


__all__ = [
    "EXTRA",
    "documentai_client",
    "firestore_client",
    "kms_client",
    "publisher_client",
    "require",
    "secret_manager_client",
    "storage_client",
    "workflows_executions_client",
]
