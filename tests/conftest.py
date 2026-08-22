"""Fixtures compartidas: contenedor en memoria y tenant de prueba.

Todo el suite corre **sin red y sin SDKs de nube**. Si una prueba necesitara
`boto3` o `google-cloud-*`, sería señal de que el núcleo se acopló a un
adaptador.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from onboarding_generico.composer.spec import FlowSpec  # noqa: E402
from onboarding_generico.config import Settings, load_settings  # noqa: E402
from onboarding_generico.container import (  # noqa: E402
    Container,
    build_inmemory_container,
    provision_demo_tenant,
)
from onboarding_generico.domain.value_objects import ObjectRef, TenantId  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Tenant de prueba. Coincide con el formato exigido por `TenantId`.
TEST_TENANT = "acme"
TEST_PRINCIPAL = "svc-requester"

#: Ejemplos canónicos de ICAO 9303 (ERIKSSON ANNA MARIA).
TD1_CANONICAL = (
    "I<UTOD231458907<<<<<<<<<<<<<<<\n7408122F1204159UTO<<<<<<<<<<<6\nERIKSSON<<ANNA<MARIA<<<<<<<<<<"
)
TD2_CANONICAL = "I<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<\nD231458907UTO7408122F1204159<<<<<<<6"
TD3_CANONICAL = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\nL898902C36UTO7408122F1204159ZE184226B<<<<<10"
)


@pytest.fixture()
def settings() -> Settings:
    """Configuración determinista, sin leer el entorno del proceso."""
    return load_settings(
        {
            "OG_ENVIRONMENT": "test",
            "OG_CLOUD_PROVIDER": "inmemory",
            "OG_ARTIFACT_BUCKET": "og-test-artifacts",
            "OG_LOG_LEVEL": "CRITICAL",
            "OG_SESSION_TTL_SECONDS": "3600",
        }
    )


@pytest.fixture()
def tenant() -> TenantId:
    return TenantId(TEST_TENANT)


@pytest.fixture()
def other_tenant() -> TenantId:
    """Segundo tenant, para las pruebas de aislamiento criptográfico."""
    return TenantId("globex")


@pytest.fixture()
def flow_spec_document() -> dict[str, Any]:
    """Documento JSON de la spec `Standard-eKYC-Latam`."""
    with (FIXTURES / "flow_standard_ekyc_latam.json").open(encoding="utf-8") as handle:
        document: dict[str, Any] = json.load(handle)
    return document


@pytest.fixture()
def flow_spec(flow_spec_document: dict[str, Any]) -> FlowSpec:
    return FlowSpec.parse(flow_spec_document)


@pytest.fixture()
def mrz_samples() -> dict[str, Any]:
    with (FIXTURES / "mrz_samples.json").open(encoding="utf-8") as handle:
        samples: dict[str, Any] = json.load(handle)
    return samples


@pytest.fixture()
def container(settings: Settings, tenant: TenantId, flow_spec: FlowSpec) -> Iterator[Container]:
    """Contenedor en memoria con el tenant de prueba ya aprovisionado."""
    built = build_inmemory_container(settings)
    provision_demo_tenant(built, tenant, principal=TEST_PRINCIPAL)
    built.spec_registry.publish(flow_spec)
    yield built


@pytest.fixture()
def upload() -> Any:
    """Sube un objeto al almacén y devuelve `(ObjectRef, sha256, size)`."""

    def _upload(
        container: Container, tenant_id: TenantId, key: str, data: bytes
    ) -> tuple[ObjectRef, str, int]:
        ref = container.storage.put(tenant_id, key, data, content_type="image/jpeg")
        return ref, hashlib.sha256(data).hexdigest(), len(data)

    return _upload
