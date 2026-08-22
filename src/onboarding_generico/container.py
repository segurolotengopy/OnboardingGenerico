"""Composition root: construye el grafo de dependencias según `OG_CLOUD_PROVIDER`.

Es el **único** punto del código donde se decide qué adaptador implementa cada
puerto. Ni el dominio ni los casos de uso conocen el proveedor de nube; si
alguna vez lo conocieran, el hexágono estaría roto.

Los adaptadores de nube se importan **dentro** de las funciones de fábrica, de
modo que `import onboarding_generico.container` funciona sin `boto3` ni
`google-cloud-*` instalados. Solo se paga el import de un SDK cuando se
construye ese contenedor concreto.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .composer.compiler import FlowCompiler
from .composer.registry import FlowSpecRegistry
from .composer.validator import CapabilityCatalog, FlowSpecValidator
from .config import Settings, load_settings
from .crypto.envelope import EnvelopeCipher, EnvelopeFieldCipher, LocalKeyProvider, SystemRandom
from .crypto.field_policy import FieldPolicy, default_policy
from .crypto.material_cache import AtomicMaterialCache, CachedKeyProvider
from .domain.enums import Capability
from .domain.value_objects import ProviderRef, TenantId
from .errors import ConfigurationError
from .observability import StructuredLogger, configure_logging, get_logger
from .ports.config_port import AuthorizationProvider, ConfigProvider
from .ports.crypto import FieldCipher, KeyProvider
from .ports.events_bus import EventBusPort
from .ports.face_match import FaceMatchPort
from .ports.human_review import HumanReviewPort
from .ports.imaging import DocumentAlignmentPort, ForgeryDetectionPort
from .ports.liveness import LivenessPort
from .ports.llm import LlmPort
from .ports.mrz_reader import MrzReaderPort
from .ports.object_storage import ObjectStorage
from .ports.ocr import OcrPort
from .ports.repository import (
    CapabilityRegistryRepository,
    FlowSpecRepository,
    IdempotencyStore,
    MutexLock,
    SessionRepository,
)
from .ports.saga import OnboardingSagaPort
from .ports.secrets import SecretsProvider
from .ports.telemetry import TelemetryPort


@dataclass(frozen=True, slots=True)
class Container:
    """Grafo de dependencias ya construido."""

    settings: Settings
    logger: StructuredLogger

    # Persistencia y almacenamiento
    sessions: SessionRepository
    capabilities: CapabilityRegistryRepository
    flow_specs: FlowSpecRepository
    locks: MutexLock
    idempotency: IdempotencyStore
    storage: ObjectStorage

    # Criptografía
    keys: KeyProvider
    cipher: FieldCipher
    field_policy: FieldPolicy
    key_cache: AtomicMaterialCache[bytes]

    # Configuración y seguridad
    config: ConfigProvider
    secrets: SecretsProvider
    authorization: AuthorizationProvider

    # Proveedores de capacidad
    ocr: OcrPort
    mrz: MrzReaderPort
    alignment: DocumentAlignmentPort
    forgery: ForgeryDetectionPort
    face_match: FaceMatchPort
    liveness: LivenessPort
    llm: LlmPort

    # Orquestación e integración
    saga: OnboardingSagaPort
    human_review: HumanReviewPort
    events: EventBusPort
    telemetry: TelemetryPort

    # Composición
    spec_registry: FlowSpecRegistry
    validator: FlowSpecValidator
    compiler: FlowCompiler

    def describe(self) -> dict[str, str]:
        """Mapa puerto → clase concreta. Útil en el arranque y en diagnósticos."""
        return {
            name: type(getattr(self, name)).__name__
            for name in (
                "sessions",
                "capabilities",
                "flow_specs",
                "locks",
                "idempotency",
                "storage",
                "keys",
                "cipher",
                "config",
                "secrets",
                "authorization",
                "ocr",
                "mrz",
                "alignment",
                "forgery",
                "face_match",
                "liveness",
                "llm",
                "saga",
                "human_review",
                "events",
                "telemetry",
            )
        }


def build_container(
    settings: Settings | None = None, *, env: Mapping[str, str] | None = None
) -> Container:
    """Construye el contenedor según `OG_CLOUD_PROVIDER`."""
    resolved = settings or load_settings(env)
    configure_logging(
        level=resolved.log_level,
        service_name=resolved.service_name,
        redact_pii=resolved.redact_pii,
    )
    if resolved.cloud_provider == "inmemory":
        return build_inmemory_container(resolved)
    if resolved.cloud_provider == "aws":
        return build_aws_container(resolved)
    if resolved.cloud_provider == "gcp":
        return build_gcp_container(resolved)
    raise ConfigurationError(
        "proveedor de nube no soportado", cloud_provider=resolved.cloud_provider
    )


def build_inmemory_container(settings: Settings) -> Container:
    """Contenedor completo en memoria, sin dependencias externas."""
    configure_logging(
        level=settings.log_level,
        service_name=settings.service_name,
        redact_pii=settings.redact_pii,
    )
    from .adapters.inmemory import (
        InMemoryAuthorizationProvider,
        InMemoryCapabilityRegistry,
        InMemoryConfigProvider,
        InMemoryDocumentAlignment,
        InMemoryEventBus,
        InMemoryFaceMatch,
        InMemoryFlowSpecRepository,
        InMemoryForgeryDetection,
        InMemoryHumanReview,
        InMemoryIdempotencyStore,
        InMemoryLiveness,
        InMemoryLlm,
        InMemoryMrzReader,
        InMemoryMutexLock,
        InMemoryObjectStorage,
        InMemoryOcrProvider,
        InMemorySaga,
        InMemorySecretsProvider,
        InMemorySessionRepository,
        InMemoryTelemetry,
    )

    key_cache: AtomicMaterialCache[bytes] = AtomicMaterialCache(
        ttl_seconds=float(settings.key_cache_ttl_seconds),
        max_entries=settings.key_cache_max_entries,
    )
    base_keys = LocalKeyProvider()
    keys: Any = CachedKeyProvider(base_keys, key_cache)
    cipher = EnvelopeFieldCipher(EnvelopeCipher(keys, random_source=SystemRandom()), keys)

    return Container(
        settings=settings,
        logger=get_logger("container", redact_pii=settings.redact_pii),
        sessions=InMemorySessionRepository(),
        capabilities=InMemoryCapabilityRegistry(),
        flow_specs=InMemoryFlowSpecRepository(),
        locks=InMemoryMutexLock(),
        idempotency=InMemoryIdempotencyStore(),
        storage=InMemoryObjectStorage(bucket=settings.artifact_bucket),
        keys=keys,
        cipher=cipher,
        field_policy=default_policy(),
        key_cache=key_cache,
        config=InMemoryConfigProvider(),
        secrets=InMemorySecretsProvider(),
        authorization=InMemoryAuthorizationProvider(),
        ocr=InMemoryOcrProvider(),
        mrz=InMemoryMrzReader(),
        alignment=InMemoryDocumentAlignment(),
        forgery=InMemoryForgeryDetection(),
        face_match=InMemoryFaceMatch(),
        liveness=InMemoryLiveness(),
        llm=InMemoryLlm(),
        saga=InMemorySaga(),
        human_review=InMemoryHumanReview(),
        events=InMemoryEventBus(),
        telemetry=InMemoryTelemetry(),
        spec_registry=FlowSpecRegistry(),
        validator=FlowSpecValidator(CapabilityCatalog()),
        compiler=FlowCompiler(),
    )


def build_aws_container(settings: Settings) -> Container:
    """Contenedor de AWS: implementación de referencia.

    Los imports son diferidos: sin `boto3` instalado, la llamada falla con
    `MissingDependencyError` explicando qué extra instalar, no con un
    `ModuleNotFoundError` al importar el paquete.
    """
    from .adapters.aws.ai import BedrockLlm, RekognitionLiveness, TextractOcr
    from .adapters.aws.orchestration import EventBridgeBus, StepFunctionsSaga
    from .adapters.aws.persistence import (
        DbEsdkFieldCipher,
        DynamoDbCapabilityRegistry,
        DynamoDbFlowSpecRepository,
        DynamoDbIdempotencyStore,
        DynamoDbMutexLock,
        DynamoDbSessionRepository,
        HierarchicalKeyProvider,
        S3ObjectStorage,
        SecretsManagerProvider,
    )
    from .adapters.inmemory import (
        InMemoryAuthorizationProvider,
        InMemoryConfigProvider,
        InMemoryHumanReview,
        InMemoryTelemetry,
    )
    from .adapters.providers.cv_providers import InsightFaceMatch, OpenCvAlignment, TruForForgery
    from .adapters.providers.local_mrz import LocalMrzReader

    key_cache: AtomicMaterialCache[bytes] = AtomicMaterialCache(
        ttl_seconds=float(settings.key_cache_ttl_seconds),
        max_entries=settings.key_cache_max_entries,
    )
    keys: Any = CachedKeyProvider(HierarchicalKeyProvider(settings), key_cache)

    return Container(
        settings=settings,
        logger=get_logger("container", redact_pii=settings.redact_pii),
        sessions=DynamoDbSessionRepository(settings),
        capabilities=DynamoDbCapabilityRegistry(settings),
        flow_specs=DynamoDbFlowSpecRepository(settings),
        locks=DynamoDbMutexLock(settings),
        idempotency=DynamoDbIdempotencyStore(settings),
        storage=S3ObjectStorage(settings),
        keys=keys,
        cipher=DbEsdkFieldCipher(settings, keys),
        field_policy=default_policy(),
        key_cache=key_cache,
        # La autorización vive en el núcleo, no en el gateway: así es portable.
        config=InMemoryConfigProvider(),
        secrets=SecretsManagerProvider(settings),
        authorization=InMemoryAuthorizationProvider(),
        ocr=TextractOcr(settings),
        mrz=LocalMrzReader(),
        alignment=OpenCvAlignment(),
        forgery=TruForForgery(),
        face_match=InsightFaceMatch(),
        liveness=RekognitionLiveness(settings),
        llm=BedrockLlm(settings),
        saga=StepFunctionsSaga(settings),
        # HITL propio: A2I no admite clientes nuevos.
        human_review=InMemoryHumanReview(),
        events=EventBridgeBus(settings),
        telemetry=InMemoryTelemetry(),
        spec_registry=FlowSpecRegistry(),
        validator=FlowSpecValidator(CapabilityCatalog()),
        compiler=FlowCompiler(),
    )


def build_gcp_container(settings: Settings) -> Container:
    """Contenedor de GCP: alternativa por adaptadores.

    Diferencias estructurales frente a AWS, no cosméticas:

    - `LivenessPort` lo cubre un **SaaS certificado**, no un servicio de la
      nube: GCP no tiene liveness facial gestionado.
    - El aislamiento multi-tenant descansa **solo** en el cifrado con AAD: no
      existe equivalente de `dynamodb:LeadingKeys`.
    - La saga usa el patrón de persistir y relanzar para las esperas largas.
    """
    from .adapters.gcp.ai import ClaudeOnVertexLlm, DocumentAiOcr
    from .adapters.gcp.orchestration import CloudWorkflowsSaga, PubSubBus
    from .adapters.gcp.persistence import (
        FirestoreCapabilityRegistry,
        FirestoreFlowSpecRepository,
        FirestoreIdempotencyStore,
        FirestoreMutexLock,
        FirestoreSessionRepository,
        GcsObjectStorage,
        SecretManagerProvider,
        TinkFieldCipher,
        TinkKeyProvider,
    )
    from .adapters.inmemory import (
        InMemoryAuthorizationProvider,
        InMemoryConfigProvider,
        InMemoryHumanReview,
        InMemoryTelemetry,
    )
    from .adapters.providers.cv_providers import InsightFaceMatch, OpenCvAlignment, TruForForgery
    from .adapters.providers.local_mrz import LocalMrzReader
    from .adapters.providers.saas_liveness_client import SaasLivenessClient

    key_cache: AtomicMaterialCache[bytes] = AtomicMaterialCache(
        ttl_seconds=float(settings.key_cache_ttl_seconds),
        max_entries=settings.key_cache_max_entries,
    )
    keys: Any = CachedKeyProvider(TinkKeyProvider(settings), key_cache)

    return Container(
        settings=settings,
        logger=get_logger("container", redact_pii=settings.redact_pii),
        sessions=FirestoreSessionRepository(settings),
        capabilities=FirestoreCapabilityRegistry(settings),
        flow_specs=FirestoreFlowSpecRepository(settings),
        locks=FirestoreMutexLock(settings),
        idempotency=FirestoreIdempotencyStore(settings),
        storage=GcsObjectStorage(settings),
        keys=keys,
        cipher=TinkFieldCipher(settings, keys),
        field_policy=default_policy(),
        key_cache=key_cache,
        config=InMemoryConfigProvider(),
        secrets=SecretManagerProvider(settings),
        authorization=InMemoryAuthorizationProvider(),
        ocr=DocumentAiOcr(settings),
        mrz=LocalMrzReader(),
        alignment=OpenCvAlignment(),
        forgery=TruForForgery(),
        face_match=InsightFaceMatch(),
        liveness=SaasLivenessClient(settings),
        llm=ClaudeOnVertexLlm(settings),
        saga=CloudWorkflowsSaga(settings),
        human_review=InMemoryHumanReview(),
        events=PubSubBus(settings),
        telemetry=InMemoryTelemetry(),
        spec_registry=FlowSpecRegistry(),
        validator=FlowSpecValidator(CapabilityCatalog()),
        compiler=FlowCompiler(),
    )


def provision_demo_tenant(
    container: Container,
    tenant_id: TenantId,
    *,
    principal: str = "svc-requester",
    countries: tuple[str, ...] = ("MX", "BO", "PY"),
    jurisdiction: str = "MX",
) -> None:
    """Aprovisiona un tenant con el catálogo de la spec `Standard-eKYC-Latam`.

    Solo funciona con adaptadores que exponen las utilidades de alta
    (`register_tenant`, `grant`): es decir, en memoria. Es lo que usan las
    pruebas y el arranque local, nunca producción.
    """
    config = container.config
    authorization = container.authorization
    if not hasattr(config, "register_tenant") or not hasattr(authorization, "grant"):
        raise ConfigurationError(
            "el aprovisionamiento de demostración exige adaptadores en memoria",
            cloud_provider=container.settings.cloud_provider,
        )
    config.register_tenant(tenant_id, {"jurisdiction": jurisdiction})
    authorization.grant(principal, tenant_id, "*")

    catalog: tuple[tuple[Capability, str, tuple[str, ...]], ...] = (
        (Capability.DOCUMENT_ALIGNMENT, "opencv_alignment", ()),
        (Capability.OCR_DOCUMENT, "textract_ocr", ("documentai_ocr", "tesseract_ocr")),
        (Capability.MRZ_PARSE, "local_mrz", ()),
        (Capability.EXTRACTION_SEMANTIC, "claude_primary", ("claude_secondary",)),
        (Capability.VALIDATION_CROSSFIELD, "internal_crossfield", ()),
        (Capability.FORGERY_DETECTION, "trufor_forgery", ()),
        (Capability.BIOMETRICS_LIVENESS, "saas_liveness", ()),
        (Capability.BIOMETRICS_FACEMATCH, "insightface_match", ("rekognition_facematch",)),
    )
    for capability, primary, fallbacks in catalog:
        for provider_id in (primary, *fallbacks):
            container.capabilities.register_provider(
                capability,
                ProviderRef(provider_id=provider_id, version="1.0.0"),
                countries=[*list(countries), "*"],
                document_types=["*"],
                active=True,
            )
        container.capabilities.bind_tenant(
            tenant_id, capability, primary=primary, fallbacks=list(fallbacks)
        )


__all__ = [
    "Container",
    "build_aws_container",
    "build_container",
    "build_gcp_container",
    "build_inmemory_container",
    "provision_demo_tenant",
]
