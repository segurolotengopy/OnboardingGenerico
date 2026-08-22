"""Conformidad de contrato de los adaptadores.

Tres cosas se verifican aquí y no en las pruebas unitarias:

1. **Cobertura**: existe un adaptador en memoria para *cada* puerto declarado.
   Un puerto sin doble de prueba es un puerto que nadie ejercita.
2. **Firma**: cada implementación respeta el nombre y los parámetros del
   método abstracto. Un adaptador que renombra un parámetro compila y falla
   en producción.
3. **Arquitectura**: importar el paquete no arrastra SDKs de nube, el núcleo
   no importa adaptadores, y los puertos no exponen primitivas de DynamoDB.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path
from typing import Any

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import onboarding_generico  # noqa: E402
from onboarding_generico.adapters import inmemory  # noqa: E402
from onboarding_generico.crypto.envelope import (  # noqa: E402
    EnvelopeCipher,
    EnvelopeFieldCipher,
    LocalKeyProvider,
    SystemRandom,
)
from onboarding_generico.crypto.material_cache import AtomicMaterialCache  # noqa: E402
from onboarding_generico.domain.value_objects import ObjectRef, SessionId, TenantId  # noqa: E402
from onboarding_generico.ports import ALL_PORTS  # noqa: E402

_KEYS = LocalKeyProvider(b"clave-raiz-de-prueba-32-bytes-xx")


def _instances() -> list[Any]:
    """Una instancia de cada adaptador en memoria, más los de criptografía."""
    return [
        inmemory.InMemoryAuthorizationProvider(),
        inmemory.InMemoryCapabilityRegistry(),
        inmemory.InMemoryConfigProvider(),
        inmemory.InMemoryDocumentAlignment(),
        inmemory.InMemoryEventBus(),
        inmemory.InMemoryFaceMatch(),
        inmemory.InMemoryFlowSpecRepository(),
        inmemory.InMemoryForgeryDetection(),
        inmemory.InMemoryHumanReview(),
        inmemory.InMemoryIdempotencyStore(),
        inmemory.InMemoryLiveness(),
        inmemory.InMemoryLlm(),
        inmemory.InMemoryMrzReader(),
        inmemory.InMemoryMutexLock(),
        inmemory.InMemoryObjectStorage(),
        inmemory.InMemoryOcrProvider(),
        inmemory.InMemorySaga(),
        inmemory.InMemorySecretsProvider(),
        inmemory.InMemorySessionRepository(),
        inmemory.InMemoryTelemetry(),
        _KEYS,
        EnvelopeFieldCipher(EnvelopeCipher(_KEYS), _KEYS),
        AtomicMaterialCache(),
        SystemRandom(),
    ]


ADAPTERS = _instances()


# --------------------------------------------------------------------------
# Cobertura de puertos
# --------------------------------------------------------------------------


@pytest.mark.parametrize("port", ALL_PORTS, ids=lambda p: p.__name__)
def test_every_port_has_an_in_memory_adapter(port: type) -> None:
    matches = [a for a in ADAPTERS if isinstance(a, port)]
    assert matches, f"no hay adaptador en memoria para {port.__name__}"


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: type(a).__name__)
def test_no_abstract_method_is_left_unimplemented(adapter: Any) -> None:
    """Instanciar ya lo garantiza en Python, pero se comprueba explícitamente."""
    pending = getattr(type(adapter), "__abstractmethods__", frozenset())
    assert pending == frozenset(), f"{type(adapter).__name__} deja métodos sin implementar"


@pytest.mark.parametrize("adapter", ADAPTERS, ids=lambda a: type(a).__name__)
def test_signatures_match_the_port(adapter: Any) -> None:
    """Renombrar un parámetro rompe a los llamadores por palabra clave."""
    for port in ALL_PORTS:
        if not isinstance(adapter, port):
            continue
        for name in getattr(port, "__abstractmethods__", frozenset()):
            port_signature = inspect.signature(getattr(port, name))
            adapter_signature = inspect.signature(getattr(type(adapter), name))
            port_params = [p for p in port_signature.parameters.values() if p.name != "self"]
            adapter_params = [p for p in adapter_signature.parameters.values() if p.name != "self"]
            assert len(port_params) == len(adapter_params), (
                f"{type(adapter).__name__}.{name} cambia el número de parámetros de "
                f"{port.__name__}.{name}"
            )
            for expected, actual in zip(port_params, adapter_params, strict=True):
                assert expected.kind == actual.kind, (
                    f"{type(adapter).__name__}.{name}: el parámetro '{actual.name}' cambia de "
                    f"clase respecto a {port.__name__}"
                )
                if expected.kind is inspect.Parameter.KEYWORD_ONLY:
                    assert expected.name == actual.name, (
                        f"{type(adapter).__name__}.{name}: el parámetro por palabra clave "
                        f"'{expected.name}' fue renombrado a '{actual.name}'"
                    )
                    assert expected.default == actual.default, (
                        f"{type(adapter).__name__}.{name}: el valor por defecto de "
                        f"'{expected.name}' no coincide con el del puerto"
                    )


# --------------------------------------------------------------------------
# Comportamiento común exigido por los contratos
# --------------------------------------------------------------------------


def test_session_repository_contract(tenant: TenantId) -> None:
    from onboarding_generico.errors import SessionNotFoundError

    repository = inmemory.InMemorySessionRepository()
    missing = SessionId.generate()
    assert repository.find(tenant, missing) is None
    with pytest.raises(SessionNotFoundError):
        repository.get(tenant, missing)


def test_object_storage_contract(tenant: TenantId, other_tenant: TenantId) -> None:
    from onboarding_generico.errors import (
        IntegrityError,
        ObjectNotFoundError,
        TenantIsolationError,
    )

    storage = inmemory.InMemoryObjectStorage(bucket="og-test-artifacts")
    ref = storage.put(tenant, "docs/1", b"contenido", content_type="image/jpeg")

    # El adaptador prefija con el tenant: el llamador no puede escaparse.
    assert ref.key.startswith(f"tenants/{tenant.value}/")
    assert storage.get(tenant, ref) == b"contenido"
    assert storage.exists(tenant, ref) is True

    # I6: el sha256 declarado se verifica antes de devolver los bytes.
    corrupted = ObjectRef.build(
        scheme="mem", bucket=ref.bucket, key=ref.key, sha256="0" * 64, size_bytes=ref.size_bytes
    )
    with pytest.raises(IntegrityError):
        storage.get(tenant, corrupted)

    # Aislamiento: la referencia de otro tenant no se lee.
    with pytest.raises(TenantIsolationError):
        storage.get(other_tenant, ref)
    assert storage.exists(other_tenant, ref) is False

    # Salto de directorio rechazado.
    with pytest.raises(TenantIsolationError):
        storage.put(tenant, "../../otro/1", b"x")

    assert storage.delete_many(tenant, [ref]) == 1
    with pytest.raises(ObjectNotFoundError):
        storage.get(tenant, ref)


def test_object_storage_presign_roundtrip(tenant: TenantId) -> None:
    storage = inmemory.InMemoryObjectStorage()
    url = storage.presign_put(tenant, "docs/2", ttl_seconds=60, max_bytes=1024)
    assert "token=" in url and "max_bytes=1024" in url
    assert storage.resolve_presigned(url) == f"tenants/{tenant.value}/docs/2"
    assert storage.resolve_presigned("mem://b/k?token=falso") is None


def test_mutex_lock_contract(tenant: TenantId) -> None:
    from onboarding_generico.errors import LockAcquisitionError

    lock = inmemory.InMemoryMutexLock()
    token = lock.acquire(tenant, "purge", ttl_seconds=60)
    assert lock.is_held(tenant, "purge") is True
    with pytest.raises(LockAcquisitionError):
        lock.acquire(tenant, "purge")
    # El token de vallado impide que un titular caducado libere el lock ajeno.
    assert lock.release(tenant, "purge", "fence-falso") is False
    assert lock.release(tenant, "purge", token) is True
    assert lock.is_held(tenant, "purge") is False


def test_mutex_lock_expires(tenant: TenantId) -> None:
    clock = {"now": 0.0}
    lock = inmemory.InMemoryMutexLock(clock=lambda: clock["now"])
    lock.acquire(tenant, "purge", ttl_seconds=10)
    clock["now"] = 11.0
    assert lock.is_held(tenant, "purge") is False
    assert lock.acquire(tenant, "purge")


def test_idempotency_store_contract(tenant: TenantId) -> None:
    store = inmemory.InMemoryIdempotencyStore()
    assert store.reserve(tenant, "session", "k1") is True
    assert store.reserve(tenant, "session", "k1") is False
    assert store.result_for(tenant, "session", "k1") is None
    store.record_result(tenant, "session", "k1", {"session_id": "s1"})
    assert store.result_for(tenant, "session", "k1") == {"session_id": "s1"}
    # El alcance incluye el tenant.
    assert store.reserve(TenantId("globex"), "session", "k1") is True


def test_capability_registry_contract(tenant: TenantId) -> None:
    from onboarding_generico.domain.enums import Capability
    from onboarding_generico.domain.value_objects import ProviderRef

    registry = inmemory.InMemoryCapabilityRegistry()
    registry.register_provider(
        Capability.OCR_DOCUMENT,
        ProviderRef("textract_ocr", "1.5.2"),
        countries=["MX", "BO"],
        document_types=["*"],
    )
    registry.register_provider(
        Capability.OCR_DOCUMENT,
        ProviderRef("documentai_ocr", "1.0.0"),
        countries=["*"],
        document_types=["*"],
        active=False,
    )
    assert registry.is_registered(Capability.OCR_DOCUMENT, "documentai_ocr") is True
    assert registry.is_active(Capability.OCR_DOCUMENT, "documentai_ocr") is False

    # Sin vínculo del tenant, la resolución es vacía: `CapabilityNotProvisioned`.
    assert (
        registry.resolve_provider(
            tenant, Capability.OCR_DOCUMENT, country="MX", document_type="INE_2019"
        )
        == ()
    )

    registry.bind_tenant(
        tenant, Capability.OCR_DOCUMENT, primary="textract_ocr", fallbacks=["documentai_ocr"]
    )
    chain = registry.resolve_provider(
        tenant, Capability.OCR_DOCUMENT, country="MX", document_type="INE_2019"
    )
    # El proveedor inactivo se descarta de la cadena.
    assert [p.provider_id for p in chain] == ["textract_ocr"]
    # Y el país no cubierto también.
    assert (
        registry.resolve_provider(
            tenant, Capability.OCR_DOCUMENT, country="FR", document_type="PASSPORT"
        )
        == ()
    )
    assert Capability.OCR_DOCUMENT in registry.tenant_capabilities(tenant)


def test_saga_resume_is_idempotent(tenant: TenantId) -> None:
    """Eventarc no garantiza orden ni replay: reanudar dos veces no avanza dos."""
    saga = inmemory.InMemorySaga()
    handle = saga.start_verification(tenant, SessionId.generate(), plan={"content_hash": "h"})
    token = saga.await_manual_decision(handle, reason="FACE_GREY_BAND")
    assert saga.status(handle).suspended is True
    saga.resume(token, {"outcome": "APPROVED"})
    saga.resume(token, {"outcome": "REJECTED"})
    status = saga.status(handle)
    assert status.state == "RUNNING"
    assert status.context["outcome"] == "APPROVED"


def test_saga_rejects_binaries_in_the_context(tenant: TenantId) -> None:
    """Ningún binario puede viajar por el estado del orquestador."""
    from onboarding_generico.errors import ValidationError

    saga = inmemory.InMemorySaga()
    with pytest.raises(ValidationError):
        saga.start_verification(
            tenant, SessionId.generate(), plan={}, context={"image": b"\x00" * 10}
        )


def test_event_bus_deduplicates_and_orders(tenant: TenantId) -> None:
    from onboarding_generico.ports.events_bus import IntegrationEvent

    bus = inmemory.InMemoryEventBus()
    events = [
        IntegrationEvent(
            event_id=f"e{i}",
            event_type="og.step.completed",
            tenant_id=tenant.value,
            session_id="s1",
            sequence=i,
            occurred_at="2026-08-21T00:00:00Z",
        )
        for i in (2, 0, 1)
    ]
    bus.publish_batch(events)
    bus.publish(events[0])  # republicación: consumidor idempotente
    published = bus.published_for(tenant, "s1")
    assert [e.sequence for e in published] == [0, 1, 2]


def test_telemetry_rejects_forbidden_dimensions() -> None:
    """Una dimensión `subject_ref` convertiría la telemetría en un índice de personas."""
    from onboarding_generico.errors import ValidationError

    telemetry = inmemory.InMemoryTelemetry()
    telemetry.increment("sessions", dimensions={"country": "MX"})
    with pytest.raises(ValidationError):
        telemetry.increment("sessions", dimensions={"subject_ref": "subj-1"})
    with pytest.raises(ValidationError):
        telemetry.observe("latency", 1.0, dimensions={"session_id": "s1"})
    assert telemetry.snapshot()["sessions{country=MX}"] == 1.0


def test_config_provider_enforces_bolivian_rule(tenant: TenantId) -> None:
    """Regla codificada en el motor, no una nota en un manual."""
    from onboarding_generico.errors import ConfigurationError

    config = inmemory.InMemoryConfigProvider()
    config.register_tenant(tenant, {"jurisdiction": "BO", "decision_issuer": "MIDDLEWARE"})
    with pytest.raises(ConfigurationError):
        config.get_decision_issuer(tenant)


def test_secrets_provider_never_returns_a_silent_default() -> None:
    from onboarding_generico.errors import ConfigurationError

    secrets = inmemory.InMemorySecretsProvider()
    with pytest.raises(ConfigurationError):
        secrets.get_secret("og/no/existe")
    secrets.set_secret("og/liveness/api-key", "ficticio")
    assert secrets.get_secret("og/liveness/api-key") == "ficticio"


def test_authorization_rejects_unknown_actions(tenant: TenantId) -> None:
    from onboarding_generico.errors import AuthorizationError, ConfigurationError

    authorization = inmemory.InMemoryAuthorizationProvider()
    with pytest.raises(ConfigurationError):
        authorization.grant("svc", tenant, ["accion:inventada"])
    authorization.grant("svc", tenant, ["session:create"])
    assert authorization.authorize("svc", tenant, "session:create") is True
    assert authorization.authorize("svc", TenantId("globex"), "session:create") is False
    with pytest.raises(AuthorizationError):
        authorization.assert_authorized("svc", tenant, "tenant:purge")


# --------------------------------------------------------------------------
# Pruebas de arquitectura
# --------------------------------------------------------------------------


def test_importing_the_package_never_requires_a_cloud_sdk() -> None:
    """Ningún módulo puede importar `boto3` o `google-cloud-*` a nivel de módulo."""
    failures: list[str] = []
    for module in pkgutil.walk_packages(onboarding_generico.__path__, "onboarding_generico."):
        try:
            importlib.import_module(module.name)
        except Exception as exc:
            failures.append(f"{module.name}: {type(exc).__name__}: {exc}")
    assert failures == []


def test_no_cloud_sdk_is_loaded_after_importing_everything() -> None:
    for forbidden in ("boto3", "botocore", "google.cloud", "onnxruntime", "cv2"):
        assert forbidden not in sys.modules, f"{forbidden} se cargó al importar el paquete"


@pytest.mark.parametrize("package", ["domain", "ports", "composer", "application", "crypto"])
def test_the_core_does_not_import_adapters(package: str) -> None:
    """El núcleo no puede conocer a ningún adaptador ni a ningún SDK."""
    root = Path(onboarding_generico.__path__[0]) / package
    offending: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("import boto3", "from boto3", "google.cloud", "import cv2", "onnxruntime"):
            if needle in text:
                offending.append(f"{path.name}: {needle}")
    assert offending == []


def test_repository_port_exposes_no_dynamodb_primitives() -> None:
    """Un puerto acoplado a DynamoDB haría inviable el adaptador de Firestore.

    Se inspecciona la **superficie**: nombres de método y de parámetro. Los
    docstrings sí nombran esas primitivas, precisamente para advertir de que
    no deben aparecer aquí.
    """
    from onboarding_generico.ports.repository import (
        CapabilityRegistryRepository,
        FlowSpecRepository,
        IdempotencyStore,
        MutexLock,
        SessionRepository,
    )

    forbidden = (
        "begins_with",
        "condition_expression",
        "key_condition",
        "gsi",
        "partition_key",
        "sort_key",
        "sk",
        "pk",
        "index_name",
        "projection_expression",
        "exclusive_start_key",
        "last_evaluated_key",
    )
    surface: list[str] = []
    for port in (
        SessionRepository,
        CapabilityRegistryRepository,
        MutexLock,
        IdempotencyStore,
        FlowSpecRepository,
    ):
        for name in port.__abstractmethods__:
            surface.append(name.lower())
            surface.extend(
                parameter.lower() for parameter in inspect.signature(getattr(port, name)).parameters
            )
    for token in forbidden:
        assert token not in surface, f"el puerto de repositorio expone '{token}'"


def test_field_policy_forbids_pii_in_index_keys() -> None:
    from onboarding_generico.crypto.field_policy import default_policy
    from onboarding_generico.errors import ValidationError

    policy = default_policy()
    policy.assert_keys_are_safe(["tenant_id", "session_id", "state", "created_at"])
    with pytest.raises(ValidationError):
        policy.assert_keys_are_safe(["id_number"])
