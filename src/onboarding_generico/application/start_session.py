"""Caso de uso: iniciar una sesión de onboarding.

Secuencia:

1. Autorizar al principal **en el núcleo** (no en el gateway).
2. Resolver la especificación por (tenant, país, documento, tier). Si no hay
   spec aplicable se responde 422 y **no se crea la sesión**.
3. Verificar que el tenant tiene proveedor activo para toda capacidad de la
   spec (`CapabilityNotProvisioned` con el detalle exacto de qué falta).
4. Compilar el plan y **congelar** la referencia de spec en la sesión: una
   republicación posterior no afecta a sesiones en vuelo.
5. Emitir las URLs prefirmadas de carga directa, para que las imágenes no
   atraviesen el middleware.
6. Abrir la cadena de auditoría con el evento génesis.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

from ..domain.enums import ArtifactSlot, Capability, DocumentType, EventType, SessionState
from ..domain.events import AuditChain
from ..domain.session import OnboardingSession, Step
from ..domain.value_objects import SessionId, SubjectRef, TenantId
from ..errors import CapabilityNotProvisionedError, ValidationError
from ..observability import correlation_scope, get_logger

if TYPE_CHECKING:  # pragma: no cover - solo para tipado
    from ..composer.compiler import ExecutionPlan
    from ..container import Container

_logger = get_logger("application.start_session")


@dataclass(frozen=True, slots=True)
class StartSessionCommand:
    """Petición de creación de sesión."""

    tenant_id: str
    subject_ref: str
    country: str
    document_type: str
    tier: str = "IAL2"
    external_ref: str | None = None
    principal: str = "svc-requester"
    idempotency_key: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True, slots=True)
class UploadTarget:
    """Destino de carga directa para una ranura de artefacto."""

    slot: str
    url: str
    max_bytes: int
    mime_types: tuple[str, ...]
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class StartSessionResult:
    """Respuesta del caso de uso."""

    session_id: str
    state: str
    spec_key: str
    spec_version: str
    spec_hash: str
    upload_targets: tuple[UploadTarget, ...]
    plan: Mapping[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "spec": {
                "key": self.spec_key,
                "version": self.spec_version,
                "content_hash": self.spec_hash,
            },
            "upload_targets": [
                {
                    "slot": t.slot,
                    "url": t.url,
                    "max_bytes": t.max_bytes,
                    "mime_types": list(t.mime_types),
                    "expires_in_seconds": t.expires_in_seconds,
                }
                for t in self.upload_targets
            ],
            "warnings": list(self.warnings),
        }


class StartSession:
    """Orquesta la creación de la sesión sobre los puertos."""

    __slots__ = ("_c",)

    def __init__(self, container: Container) -> None:
        self._c = container

    def execute(self, command: StartSessionCommand) -> StartSessionResult:
        tenant_id = TenantId(command.tenant_id)
        with correlation_scope(correlation_id=command.correlation_id, tenant_id=tenant_id.value):
            self._c.authorization.assert_authorized(command.principal, tenant_id, "session:create")
            if not self._c.config.is_tenant_active(tenant_id):
                raise ValidationError("el tenant no está activo", field="tenant_id")

            document_type = _coerce_document_type(command.document_type)
            resolved = self._c.spec_registry.resolve(
                tenant_id=tenant_id.value,
                country=command.country,
                document_type=str(document_type),
                tier=command.tier,
            )
            spec = resolved.spec

            self._assert_provisioned(tenant_id, spec, command.country, str(document_type))

            report = self._c.validator.validate(spec)
            report.raise_if_failed()
            plan = self._compile(spec, report.resolved_capabilities)

            steps = tuple(
                Step(
                    step_id=step.step_id,
                    capability=Capability(step.capability),
                    depends_on=step.depends_on,
                    required=step.required,
                )
                for step in plan.steps
            )
            session = OnboardingSession.start(
                tenant_id=tenant_id,
                subject=SubjectRef(command.subject_ref),
                country=command.country,
                document_type=document_type,
                tier=command.tier,
                spec_ref=resolved.ref,
                steps=steps,
                ttl_seconds=self._c.settings.session_ttl_seconds,
                external_ref=command.external_ref,
            )
            self._c.sessions.save(session, expected_version=0)

            chain = AuditChain(tenant_id.value, session.session_id.value)
            event = chain.append(
                EventType.SESSION_CREATED,
                actor=command.principal,
                attributes={
                    "country": command.country,
                    "document_type": str(document_type),
                    "tier": command.tier,
                    "spec_key": resolved.ref.key,
                    "spec_version": resolved.ref.version,
                },
            )
            self._c.sessions.append_audit_event(event)

            targets = self._upload_targets(tenant_id, session.session_id, spec)
            self._c.telemetry.increment(
                "sessions_started",
                dimensions={"country": command.country, "tier": command.tier},
            )
            _logger.info(
                "sesión creada",
                spec_key=resolved.ref.key,
                spec_version=resolved.ref.version,
                step_count=len(steps),
                country=command.country,
            )

            return StartSessionResult(
                session_id=session.session_id.value,
                state=str(SessionState.CREATED),
                spec_key=resolved.ref.key,
                spec_version=resolved.ref.version,
                spec_hash=resolved.ref.content_hash,
                upload_targets=targets,
                plan=plan.as_dict(),
                warnings=plan.warnings,
            )

    # -- Auxiliares --------------------------------------------------------

    def _assert_provisioned(
        self, tenant_id: TenantId, spec: Any, country: str, document_type: str
    ) -> None:
        missing: list[str] = []
        for step in spec.steps:
            chain = self._c.capabilities.resolve_provider(
                tenant_id,
                step.capability.capability,
                country=country,
                document_type=document_type,
            )
            if not chain:
                missing.append(str(step.capability.capability))
        if missing:
            raise CapabilityNotProvisionedError(
                "el tenant no tiene proveedor activo para todas las capacidades de la spec",
                tenant_id=tenant_id.value,
                missing_capabilities=sorted(set(missing)),
                spec=spec.key,
            )

    def _compile(self, spec: Any, resolved_capabilities: Mapping[str, str]) -> ExecutionPlan:
        from ..composer.compiler import FlowCompiler

        return FlowCompiler(resolved_capabilities).compile(spec)

    def _upload_targets(
        self, tenant_id: TenantId, session_id: SessionId, spec: Any
    ) -> tuple[UploadTarget, ...]:
        ttl = self._c.settings.presign_ttl_seconds
        targets: list[UploadTarget] = []
        for artifact in spec.required_artifacts:
            key = f"sessions/{session_id.value}/{artifact.slot}"
            url = self._c.storage.presign_put(
                tenant_id,
                key,
                ttl_seconds=ttl,
                content_type=artifact.mime_types[0],
                max_bytes=min(artifact.max_bytes, self._c.settings.max_artifact_bytes),
            )
            targets.append(
                UploadTarget(
                    slot=str(artifact.slot),
                    url=url,
                    max_bytes=min(artifact.max_bytes, self._c.settings.max_artifact_bytes),
                    mime_types=artifact.mime_types,
                    expires_in_seconds=ttl,
                )
            )
        return tuple(targets)


def _coerce_document_type(value: str) -> DocumentType:
    try:
        return DocumentType(value.strip().upper())
    except ValueError as exc:
        known = ", ".join(sorted(d.value for d in DocumentType))
        raise ValidationError(
            f"tipo de documento desconocido '{value}'; admitidos: {known}", field="document_type"
        ) from exc


__all__ = [
    "ArtifactSlot",
    "StartSession",
    "StartSessionCommand",
    "StartSessionResult",
    "UploadTarget",
]
