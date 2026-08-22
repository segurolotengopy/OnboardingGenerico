"""Puntos de entrada de GCP: aplicación HTTP de Cloud Run y trabajo de purga.

Diferencia estructural con AWS, no cosmética: **GCP API Gateway solo admite
autenticación declarativa** (API keys, JWT contra emisores configurados,
cuentas de servicio) y no ejecuta código arbitrario por petición. No hay
equivalente del Lambda Authorizer, de modo que la autorización se aplica como
**middleware in-process** de esta aplicación. Eso resulta más portable, no
menos: saca la autorización del adaptador de infraestructura y la lleva al
núcleo.

También se pierde el caché de authorizer de API Gateway (hasta 3.600 s); se
sustituye por caché en proceso con TTL.

FastAPI se importa de forma diferida dentro de `create_app()`, para que este
módulo se pueda importar sin el extra `gcp` instalado.
"""

from __future__ import annotations

from typing import Any, Mapping

from ...application.purge_tenant_data import PurgeCommand, PurgeTenantData
from ...application.resolve_decision import ResolveDecision, ResolveDecisionCommand
from ...application.start_session import StartSession, StartSessionCommand
from ...application.submit_document import SubmitDocument, SubmitDocumentCommand
from ...application.submit_selfie import SubmitSelfie, SubmitSelfieCommand
from ...container import Container, build_container
from ...domain.value_objects import TenantId
from ...errors import AuthorizationError, MissingDependencyError, OnboardingError
from ...observability import correlation_scope, get_logger, new_correlation_id

_logger = get_logger("handlers.gcp")

_container: Container | None = None


def get_container() -> Container:
    """Contenedor reutilizado entre peticiones de la misma instancia."""
    global _container
    if _container is None:
        _container = build_container()
    return _container


def reset_container(container: Container | None = None) -> None:
    """Inyecta o limpia el contenedor. Se usa en pruebas."""
    global _container
    _container = container


def _require_fastapi() -> tuple[Any, Any]:
    try:
        import fastapi  # noqa: PLC0415
        from fastapi.responses import JSONResponse  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depende del entorno
        raise MissingDependencyError("fastapi", "gcp") from exc
    return fastapi, JSONResponse


def create_app() -> Any:
    """Construye la aplicación FastAPI que sirve Cloud Run."""
    fastapi, JSONResponse = _require_fastapi()
    app = fastapi.FastAPI(title="Onboarding Genérico", version="1.0.0")
    container = get_container()

    @app.middleware("http")
    async def authorization_middleware(request: Any, call_next: Any) -> Any:
        """Autorización **en el núcleo**, porque el gateway no la puede hacer."""
        correlation_id = request.headers.get("x-correlation-id") or new_correlation_id()
        principal = request.headers.get("x-og-principal", "")
        tenant_raw = request.headers.get("x-og-tenant", "")
        if request.url.path.startswith("/healthz"):
            return await call_next(request)
        if not principal or not tenant_raw:
            return JSONResponse(
                status_code=401,
                content={"error": {"code": "OG_UNAUTHORIZED", "message": "faltan credenciales"}},
            )
        try:
            container.authorization.assert_authorized(
                principal, TenantId(tenant_raw), _action_for(request.method, request.url.path)
            )
        except AuthorizationError as exc:
            return JSONResponse(status_code=403, content={"error": exc.to_dict()})
        with correlation_scope(correlation_id=correlation_id, tenant_id=tenant_raw):
            request.state.principal = principal
            request.state.tenant_id = tenant_raw
            request.state.correlation_id = correlation_id
            return await call_next(request)

    @app.exception_handler(OnboardingError)
    async def domain_error_handler(request: Any, exc: OnboardingError) -> Any:
        _logger.warning("error de dominio", code=exc.code)
        return JSONResponse(status_code=exc.http_status, content={"error": exc.to_dict()})

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok", "adapters": container.describe()}

    @app.post("/v1/sessions", status_code=201)
    async def create_session(payload: dict[str, Any], request: Any) -> dict[str, Any]:
        result = StartSession(container).execute(
            StartSessionCommand(
                tenant_id=request.state.tenant_id,
                subject_ref=str(payload["subject_ref"]),
                country=str(payload["country"]),
                document_type=str(payload["document_type"]),
                tier=str(payload.get("tier", "IAL2")),
                external_ref=payload.get("external_ref"),
                principal=request.state.principal,
                correlation_id=request.state.correlation_id,
            )
        )
        return result.as_dict()

    @app.post("/v1/sessions/{session_id}/artifacts")
    async def submit_artifact(
        session_id: str, payload: dict[str, Any], request: Any
    ) -> dict[str, Any]:
        result = SubmitDocument(container).execute(
            SubmitDocumentCommand(
                tenant_id=request.state.tenant_id,
                session_id=session_id,
                slot=str(payload["slot"]),
                object_key=str(payload["object_key"]),
                sha256=str(payload["sha256"]),
                content_type=str(payload.get("content_type", "image/jpeg")),
                size_bytes=int(payload.get("size_bytes", 0)),
                principal=request.state.principal,
                correlation_id=request.state.correlation_id,
            )
        )
        return result.as_dict()

    @app.post("/v1/sessions/{session_id}/selfie")
    async def submit_selfie(
        session_id: str, payload: dict[str, Any], request: Any
    ) -> dict[str, Any]:
        result = SubmitSelfie(container).execute(
            SubmitSelfieCommand(
                tenant_id=request.state.tenant_id,
                session_id=session_id,
                object_key=str(payload["object_key"]),
                sha256=str(payload["sha256"]),
                liveness_session_id=payload.get("liveness_session_id"),
                size_bytes=int(payload.get("size_bytes", 0)),
                principal=request.state.principal,
                correlation_id=request.state.correlation_id,
            )
        )
        return result.as_dict()

    @app.post("/v1/sessions/{session_id}/decision")
    async def decide(session_id: str, request: Any) -> dict[str, Any]:
        result = ResolveDecision(container).execute(
            ResolveDecisionCommand(
                tenant_id=request.state.tenant_id,
                session_id=session_id,
                principal=request.state.principal,
                correlation_id=request.state.correlation_id,
            )
        )
        return result.as_dict()

    return app


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


def purge_job(payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Cloud Run job de purga, disparado por Cloud Scheduler.

    Se ejecuta como job y no como servicio a propósito: la purga puede durar
    más que el timeout de petición de un servicio, y su unidad de trabajo es
    un barrido completo, no una petición.
    """
    data = dict(payload or {})
    container = get_container()
    with correlation_scope(correlation_id=str(data.get("correlation_id") or new_correlation_id())):
        result = PurgeTenantData(container).execute(
            PurgeCommand(
                tenant_id=str(data["tenant_id"]),
                principal=str(data.get("principal", "svc-gdpr")),
                session_id=data.get("session_id"),
                shred_tenant_key=bool(data.get("shred_tenant_key", False)),
                dry_run=bool(data.get("dry_run", False)),
            )
        )
        _logger.info(
            "purga completada",
            sessions_purged=len(result.sessions_purged),
            objects_deleted=result.objects_deleted,
            key_shredded=result.key_shredded,
        )
        return result.as_dict()


__all__ = ["create_app", "get_container", "purge_job", "reset_container"]
