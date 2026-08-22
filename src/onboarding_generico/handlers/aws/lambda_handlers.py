"""Manejadores de Lambda, todos con firma `(event, context)`.

Cinco entradas:

===================  =====================================================
Manejador            Papel
===================  =====================================================
`lambda_authorizer`  Autorizador de API Gateway (REQUEST authorizer)
`composer`           Resolución y compilación de la spec
`step_dispatch`      Ejecutor de un paso, con cadena de reserva
`gdpr_purge`         Trabajo de purga y crypto-shredding
`api_sessions`       API HTTP de sesiones
===================  =====================================================

Dos decisiones de arranque que importan:

1. El contenedor se construye **una vez por contenedor de ejecución** y se
   reutiliza entre invocaciones. Construirlo por invocación añadiría el coste
   de los clientes de boto3 a cada llamada.
2. **La lógica de autorización vive en el núcleo**, no en este archivo. El
   autorizador de Lambda es un envoltorio: GCP API Gateway no admite código
   arbitrario por petición, así que si la lógica estuviera aquí no sería
   portable.

Sobre la memoria: el rango real es **128 MB – 10.240 MB**. No hay ningún
requisito ligado a AVX-512; Lambda documenta AVX2 y `arm64` usa NEON. El
dimensionado se decide midiendo, no por instrucciones vectoriales.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...application.handle_manual_review import (
    AssignCaseCommand,
    HandleManualReview,
    ResolveCaseCommand,
)
from ...application.purge_tenant_data import PurgeCommand, PurgeTenantData
from ...application.resolve_decision import ResolveDecision, ResolveDecisionCommand
from ...application.start_session import StartSession, StartSessionCommand
from ...application.submit_document import SubmitDocument, SubmitDocumentCommand
from ...application.submit_selfie import SubmitSelfie, SubmitSelfieCommand
from ...container import Container, build_container
from ...domain.value_objects import TenantId
from ...errors import OnboardingError
from ...observability import correlation_scope, get_logger, new_correlation_id

_logger = get_logger("handlers.aws")

#: Contenedor reutilizado entre invocaciones del mismo entorno de ejecución.
_container: Container | None = None


def get_container() -> Container:
    """Devuelve el contenedor, construyéndolo en el primer arranque en frío."""
    global _container
    if _container is None:
        _container = build_container()
    return _container


def reset_container(container: Container | None = None) -> None:
    """Inyecta o limpia el contenedor. Se usa en pruebas."""
    global _container
    _container = container


# --------------------------------------------------------------------------
# Autorizador
# --------------------------------------------------------------------------


def lambda_authorizer(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    """Autorizador REQUEST de API Gateway.

    Devuelve una política IAM y un contexto con `tenant_id` y `principal`, que
    los manejadores de negocio leen. **La decisión real la toma el núcleo**
    (`AuthorizationProvider`), no este envoltorio.
    """
    container = get_container()
    headers = {k.lower(): v for k, v in dict(event.get("headers") or {}).items()}
    principal = str(headers.get("x-og-principal", ""))
    tenant_raw = str(headers.get("x-og-tenant", ""))
    method_arn = str(event.get("methodArn", "*"))

    if not principal or not tenant_raw:
        return _policy("anonymous", "Deny", method_arn, {})

    try:
        tenant_id = TenantId(tenant_raw)
        action = _action_for(str(event.get("httpMethod", "GET")), str(event.get("path", "/")))
        allowed = container.authorization.authorize(principal, tenant_id, action)
    except OnboardingError as exc:
        _logger.warning("autorización rechazada", code=exc.code)
        return _policy(principal, "Deny", method_arn, {})

    return _policy(
        principal,
        "Allow" if allowed else "Deny",
        method_arn,
        {"tenant_id": tenant_raw, "principal": principal},
    )


def _policy(
    principal: str, effect: str, resource: str, context: Mapping[str, str]
) -> dict[str, Any]:
    return {
        "principalId": principal,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}],
        },
        "context": dict(context),
        # El caché del authorizer de API Gateway llega a 3.600 s. Se pierde al
        # portar a GCP, donde hay que replicarlo en proceso con TTL.
        "usageIdentifierKey": principal,
    }


def _action_for(method: str, path: str) -> str:
    if path.endswith("/sessions") and method == "POST":
        return "session:create"
    if "/artifacts" in path or "/selfie" in path:
        return "session:submit_artifact"
    if "/decision" in path:
        return "session:decide"
    if "/reviews" in path:
        return "review:resolve" if method in {"POST", "PUT", "PATCH"} else "review:read"
    if "/purge" in path:
        return "tenant:purge"
    return "session:read"


# --------------------------------------------------------------------------
# Compositor
# --------------------------------------------------------------------------


def composer(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    """Resuelve la spec y devuelve el plan compilado más los artefactos.

    Emite ASL y YAML de Cloud Workflows a la vez: mantener ambos emisores
    ejercitados en cada compilación es lo que impide que el destino GCP se
    pudra silenciosamente.
    """
    from ...composer.compiler import FlowCompiler, check_quotas, emit_asl, emit_cloud_workflows

    container = get_container()
    body = _body(event)
    with correlation_scope(correlation_id=_correlation_id(event)):
        resolved = container.spec_registry.resolve(
            tenant_id=str(body["tenant_id"]),
            country=str(body["country"]),
            document_type=str(body["document_type"]),
            tier=str(body.get("tier", "IAL2")),
        )
        report = container.validator.validate(resolved.spec)
        report.raise_if_failed()
        plan = FlowCompiler(report.resolved_capabilities).compile(resolved.spec)
        return _ok(
            {
                "spec": {
                    "key": resolved.ref.key,
                    "version": resolved.ref.version,
                    "content_hash": resolved.ref.content_hash,
                },
                "plan": plan.as_dict(),
                "asl": emit_asl(plan),
                "cloud_workflows_yaml": emit_cloud_workflows(plan),
                "quota_findings": list(check_quotas(plan)),
                "warnings": list(plan.warnings) + [str(w) for w in report.warnings],
            }
        )


# --------------------------------------------------------------------------
# Ejecutor de pasos
# --------------------------------------------------------------------------


def step_dispatch(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    """Ejecuta un paso del plan con su cadena de proveedores de reserva.

    Recibe **punteros**, nunca binarios: el payload de Step Functions está
    limitado a 256 KiB y el de Cloud Workflows a 512 KB acumulados.
    """
    raise NotImplementedError(
        "Falta decidir el contrato de despacho por capacidad. Cada capacidad tiene una firma de "
        "entrada distinta y hay dos formas de resolverlo: un registro de funciones por capacidad "
        "en este manejador (acopla el manejador al catálogo, pero es explícito) o un despacho "
        "genérico guiado por el esquema de la capacidad (flexible, pero mueve los errores de "
        "contrato de la publicación a la ejecución). La segunda opción anula parte del valor de "
        "la comprobación V5 del validador, así que la decisión no es solo de estilo."
    )


# --------------------------------------------------------------------------
# Purga
# --------------------------------------------------------------------------


def gdpr_purge(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    """Trabajo de purga. Se dispara por EventBridge Scheduler o a mano."""
    container = get_container()
    with correlation_scope(correlation_id=_correlation_id(event)):
        result = PurgeTenantData(container).execute(
            PurgeCommand(
                tenant_id=str(event["tenant_id"]),
                principal=str(event.get("principal", "svc-gdpr")),
                session_id=event.get("session_id"),
                shred_tenant_key=bool(event.get("shred_tenant_key", False)),
                dry_run=bool(event.get("dry_run", False)),
            )
        )
        return _ok(result.as_dict())


# --------------------------------------------------------------------------
# API de sesiones
# --------------------------------------------------------------------------


def api_sessions(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    """API HTTP de sesiones, artefactos, decisión y revisión."""
    container = get_container()
    method = str(event.get("httpMethod", "GET")).upper()
    path = str(event.get("path", "/"))
    body = _body(event)
    authorizer = dict((event.get("requestContext") or {}).get("authorizer") or {})
    tenant_id = str(authorizer.get("tenant_id") or body.get("tenant_id", ""))
    principal = str(authorizer.get("principal") or body.get("principal", "svc-requester"))
    correlation_id = _correlation_id(event)

    try:
        with correlation_scope(correlation_id=correlation_id, tenant_id=tenant_id or None):
            if method == "POST" and path.endswith("/sessions"):
                result = StartSession(container).execute(
                    StartSessionCommand(
                        tenant_id=tenant_id,
                        subject_ref=str(body["subject_ref"]),
                        country=str(body["country"]),
                        document_type=str(body["document_type"]),
                        tier=str(body.get("tier", "IAL2")),
                        external_ref=body.get("external_ref"),
                        principal=principal,
                        correlation_id=correlation_id,
                    )
                )
                return _ok(result.as_dict(), status=201)

            if method == "POST" and path.endswith("/artifacts"):
                document_result = SubmitDocument(container).execute(
                    SubmitDocumentCommand(
                        tenant_id=tenant_id,
                        session_id=str(body["session_id"]),
                        slot=str(body["slot"]),
                        object_key=str(body["object_key"]),
                        sha256=str(body["sha256"]),
                        content_type=str(body.get("content_type", "image/jpeg")),
                        size_bytes=int(body.get("size_bytes", 0)),
                        principal=principal,
                        correlation_id=correlation_id,
                    )
                )
                return _ok(document_result.as_dict())

            if method == "POST" and path.endswith("/selfie"):
                selfie_result = SubmitSelfie(container).execute(
                    SubmitSelfieCommand(
                        tenant_id=tenant_id,
                        session_id=str(body["session_id"]),
                        object_key=str(body["object_key"]),
                        sha256=str(body["sha256"]),
                        liveness_session_id=body.get("liveness_session_id"),
                        size_bytes=int(body.get("size_bytes", 0)),
                        principal=principal,
                        correlation_id=correlation_id,
                    )
                )
                return _ok(selfie_result.as_dict())

            if method == "POST" and path.endswith("/decision"):
                decision = ResolveDecision(container).execute(
                    ResolveDecisionCommand(
                        tenant_id=tenant_id,
                        session_id=str(body["session_id"]),
                        principal=principal,
                        correlation_id=correlation_id,
                    )
                )
                return _ok(decision.as_dict())

            if method == "POST" and path.endswith("/reviews:next"):
                case = HandleManualReview(container).assign_next(
                    AssignCaseCommand(
                        tenant_id=tenant_id,
                        reviewer=str(body["reviewer"]),
                        principal=principal,
                        correlation_id=correlation_id,
                    )
                )
                return _ok(case.as_dict() if case else {}, status=200 if case else 204)

            if method == "POST" and path.endswith("/reviews:resolve"):
                resolution = HandleManualReview(container).resolve(
                    ResolveCaseCommand(
                        tenant_id=tenant_id,
                        case_id=str(body["case_id"]),
                        reviewer=str(body["reviewer"]),
                        outcome=str(body["outcome"]),
                        notes_digest=str(body.get("notes_digest", "")),
                        principal=principal,
                        correlation_id=correlation_id,
                    )
                )
                return _ok(resolution.as_dict())

            return _error_response(404, "OG_NOT_FOUND", "ruta no encontrada")
    except OnboardingError as exc:
        _logger.warning("error de dominio", code=exc.code, http_status=exc.http_status)
        return _error_response(exc.http_status, exc.code, exc.message, exc.details)
    except KeyError as exc:
        return _error_response(400, "OG_VALIDATION", f"falta el campo {exc}")


# --------------------------------------------------------------------------
# Auxiliares
# --------------------------------------------------------------------------


def _body(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = event.get("body")
    if raw is None:
        return {k: v for k, v in event.items() if k not in {"headers", "requestContext"}}
    if isinstance(raw, Mapping):
        return dict(raw)
    parsed = json.loads(raw)
    return dict(parsed) if isinstance(parsed, dict) else {}


def _correlation_id(event: Mapping[str, Any]) -> str:
    headers = {k.lower(): v for k, v in dict(event.get("headers") or {}).items()}
    return str(headers.get("x-correlation-id") or new_correlation_id())


def _ok(payload: Mapping[str, Any], *, status: int = 200) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(dict(payload), ensure_ascii=False, default=str),
    }


def _error_response(
    status: int, code: str, message: str, details: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {"error": {"code": code, "message": message, "details": dict(details or {})}},
            ensure_ascii=False,
            default=str,
        ),
    }


__all__ = [
    "api_sessions",
    "composer",
    "gdpr_purge",
    "get_container",
    "lambda_authorizer",
    "reset_container",
    "step_dispatch",
]
