"""Composition root for FastAPI and mounted FastMCP."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastmcp import FastMCP
from starlette.middleware.gzip import GZipMiddleware

from sidekick import __version__
from sidekick.api.body_limits import RequestBodyLimitMiddleware
from sidekick.api.change_source import OwnerAppChangeSource
from sidekick.api.companion import create_companion_router
from sidekick.api.failed_auth import FailedAuthGuard, FailedAuthLimitMiddleware
from sidekick.api.ingress_problem import problem_response
from sidekick.api.public_surface import PublicSurfaceAllowlistMiddleware
from sidekick.api.schemas import Health
from sidekick.api.unexpected_errors import UnexpectedErrorMiddleware
from sidekick.composition import Container, SessionFactory, create_container
from sidekick.mcp import MCP_MOUNT_PATH
from sidekick.mcp.request_log import McpTransportLogging
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.config import (
    ConfigurationSources,
    Settings,
    describe_configuration_sources,
    get_settings,
)
from sidekick.shared.errors.core import (
    CLIENT_INPUT_ERRORS,
    SidekickError,
)
from sidekick.shared.observability import (
    CorrelationMiddleware,
    TelemetryPort,
    configure_observability,
    safe_log_fields,
)
from sidekick.shared.readiness import is_ready

# `Container` and `create_container` live in `sidekick.composition`; they stay importable from here.
__all__ = ["Container", "create_app", "create_container"]

if TYPE_CHECKING:
    from sidekick.mcp.oauth import SidekickGitHubOAuthProxy

LOGGER = logging.getLogger("sidekick.api.routes")


def _log_configuration_sources(sources: ConfigurationSources | None = None) -> None:
    """State where this process's settings came from, once, at startup.

    A real environment variable outranks the dotenv file, which is correct and is what CI
    and containers rely on. It is also silent: the process can keep using a value that `.env`
    no longer selects. A disagreement is therefore a warning and mere absence from the file is
    not, and the record carries only names.
    """

    resolved = sources if sources is not None else describe_configuration_sources()
    found = resolved.dotenv_file_found
    dotenv_state = "(unknown)" if found is None else ("found" if found else "missing")
    LOGGER.log(
        logging.WARNING if resolved.has_disagreement else logging.INFO,
        "sidekick_configuration_sources",
        extra=safe_log_fields(
            {
                "config_environment_disagreements": ",".join(resolved.disagreeing_with_the_file)
                or "(none)",
                # Set in the process environment and not in the file. Normal in a container
                # started with env_file; not an error. Names that are set nowhere are not listed.
                "config_environment_only": ",".join(resolved.environment_only) or "(none)",
                "config_dotenv_file": dotenv_state,
            }
        ),
    )


def _oauth_proxy_of(mcp: FastMCP) -> "SidekickGitHubOAuthProxy":
    from sidekick.mcp import oauth as mcp_oauth

    if not isinstance(mcp.auth, mcp_oauth.SidekickGitHubOAuthProxy):
        raise RuntimeError("github_oauth mode requires the Sidekick OAuth proxy")
    return mcp.auth


def _add_middleware(
    app: FastAPI,
    settings: Settings,
    telemetry: TelemetryPort,
    *,
    oauth_surface: bool,
) -> None:
    """Register middleware; the first one added sits innermost."""

    # Added first, so it sits innermost: it wraps routing and therefore the mounted MCP apps
    # (sidekick.html and tools/list answers are large JSON), while the correlation and public
    # surface middleware stay outside it. Starlette's default excludes text/event-stream, so
    # SSE answers (the MCP streams) pass through unbuffered and uncompressed.
    app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)
    # The audit trail records an app request as the owner's change (MCP tools override it).
    app.add_middleware(OwnerAppChangeSource)
    # Inside the correlation middleware: an exception no handler claimed becomes a safe 500
    # envelope that carries the correlation id (see `sidekick.api.unexpected_errors`).
    app.add_middleware(UnexpectedErrorMiddleware)
    # Body ceilings and read-time budgets guard every auth mode, so they are not tied to the OAuth
    # allowlist. Added before it, so it sits inside it: a path the allowlist refuses (and a request
    # it rate-limits) is answered before any body is read.
    app.add_middleware(
        RequestBodyLimitMiddleware,
        telemetry=telemetry,
        companion=settings.companion_enabled,
        rooms=settings.enabled_room_set,
        oauth_surface=oauth_surface,
        body_read_timeout=settings.body_read_timeout_seconds,
        oauth_body_read_timeout=settings.oauth_body_read_timeout_seconds,
        max_buffered_requests=settings.max_buffered_requests,
    )
    # Outside the body limit, so a refused bearer attempt is answered before its body is read, and
    # before the application does any database work to check the token.
    app.add_middleware(
        FailedAuthLimitMiddleware,
        telemetry=telemetry,
        guard=FailedAuthGuard(
            settings.failed_auth_per_client_per_minute,
            settings.failed_auth_global_per_minute,
            reserve_per_minute=settings.failed_auth_reserve_per_minute,
        ),
    )
    if oauth_surface:
        # Added before the correlation middleware so that it sits inside it: a refused
        # request still carries a correlation id.
        app.add_middleware(
            PublicSurfaceAllowlistMiddleware,
            telemetry=telemetry,
            companion=settings.companion_enabled,
            rooms=settings.enabled_room_set,
        )
    app.add_middleware(CorrelationMiddleware, telemetry=telemetry)


def _install_exception_handlers(app: FastAPI) -> None:
    """Map every error class to a safe problem+json envelope carrying the correlation id."""

    @app.exception_handler(SidekickError)
    async def sidekick_error(request: Request, error: SidekickError) -> JSONResponse:
        if error.code == "internal_error":
            # A fault, not a client error: let the unexpected-error middleware answer it.
            raise error
        statuses = {
            "unauthorized": 401,
            "forbidden": 403,
            "not_found": 404,
            "conflict": 409,
            "processing_in_progress": 409,
            "validation_error": 422,
        }
        safe_titles = {
            "unauthorized": "Authentication required",
            "forbidden": "Forbidden",
            "not_found": "Not found",
            "conflict": "Conflict",
            "processing_in_progress": "Processing in progress",
            "validation_error": "Request validation failed",
        }
        status_code = statuses.get(error.code, 400)
        proposal_id = getattr(error, "proposal_id", None)
        return problem_response(
            request.scope,
            status=status_code,
            code=error.code,
            title=safe_titles.get(error.code, "Request failed"),
            extra=None if proposal_id is None else {"proposal_id": str(proposal_id)},
        )

    async def invalid_input(request: Request, _error: Exception) -> JSONResponse:
        """Reject a client-supplied value safely instead of surfacing a server error.

        Application services raise `InvalidInputError` for rejected client input such as an
        out-of-range page size or a cursor that does not belong to this query. The message is
        never echoed, so nothing about other owners' data can leak. Any other `ValueError` is
        a defect and ends in the unexpected-error middleware as a 500.
        """

        return problem_response(request.scope, status=400, code="bad_request", title="Bad request")

    for client_input_error in CLIENT_INPUT_ERRORS:
        app.add_exception_handler(client_input_error, invalid_input)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        error_contracts = {
            400: ("bad_request", "Bad request"),
            401: ("unauthorized", "Authentication required"),
            403: ("forbidden", "Forbidden"),
            404: ("not_found", "Not found"),
            405: ("method_not_allowed", "Method not allowed"),
            409: ("conflict", "Conflict"),
        }
        code, title = error_contracts.get(error.status_code, ("http_error", "Request failed"))
        return problem_response(
            request.scope,
            status=error.status_code,
            code=code,
            title=title,
            headers=error.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _error: RequestValidationError) -> JSONResponse:
        return problem_response(
            request.scope,
            status=422,
            code="validation_error",
            title="Request validation failed",
        )


def _add_health_routes(app: FastAPI, container: Container) -> None:
    @app.get("/health/live", response_model=Health, operation_id="getLiveness")
    def live() -> Health:
        return Health(status="ok")

    @app.get("/health/ready", response_model=Health, operation_id="getReadiness")
    def ready() -> Health | JSONResponse:
        # The database answers and the schema is at the revision this image expects; no data.
        if is_ready(container.session_factory):
            return Health(status="ok")
        return JSONResponse(status_code=503, content={"status": "unavailable"})


def create_app(
    settings: Settings | None = None,
    session_factory: SessionFactory | None = None,
    telemetry: TelemetryPort | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    resolved_telemetry = telemetry or configure_observability(resolved.environment)
    container = create_container(resolved, session_factory, resolved_telemetry)
    mcp = create_mcp_server(container)
    oauth_surface = resolved.mcp_auth_mode == "github_oauth"
    oauth_proxy = _oauth_proxy_of(mcp) if oauth_surface else None
    # A tunnelled OAuth deployment answers a plain JSON body to each POST rather than an event
    # stream, which is the form that survives an HTTP intermediary without buffering surprises.
    mcp_app = mcp.http_app(
        path="/",
        transport="streamable-http",
        stateless_http=True,
        # `None` keeps FastMCP's own default, which is what `pat` mode uses.
        json_response=True if oauth_surface else None,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with mcp_app.lifespan(mcp_app):
            _log_configuration_sources()
            try:
                yield
            finally:
                if oauth_proxy is not None:
                    await oauth_proxy.aclose()

    # The interactive docs and the schema document describe every route to anyone who can reach
    # the port, so a production instance serves neither (the schema is still built in-process for
    # the contract tools).
    serves_docs = resolved.environment != "production"
    app = FastAPI(
        title="Sidekick API",
        version=__version__,
        docs_url="/api/docs" if serves_docs else None,
        openapi_url="/api/openapi.json" if serves_docs else None,
        redoc_url="/redoc" if serves_docs else None,
        lifespan=lifespan,
    )
    app.state.container = container
    _add_middleware(
        app,
        resolved,
        resolved_telemetry,
        oauth_surface=oauth_surface,
    )

    _install_exception_handlers(app)

    if resolved.companion_enabled:
        app.include_router(create_companion_router(rooms=resolved.enabled_room_set))

    _add_health_routes(app, container)

    if oauth_proxy is not None:
        from sidekick.mcp.oauth import root_well_known_routes

        # FastMCP requires discovery documents at the host root when it is mounted under a
        # prefix; the copies inside `mcp_app` would be reachable only below `/mcp`.
        app.router.routes.extend(root_well_known_routes(oauth_proxy))
    app.mount(MCP_MOUNT_PATH, McpTransportLogging(mcp_app))

    return app


def __getattr__(name: str) -> FastAPI:
    """``sidekick.api.app:app`` for a server that imports the attribute (the Dockerfile's uvicorn).

    The application is built on first access, not on import: a process that imports this module
    only for `create_container` (the stdio entrance, the worker) needs no settings to do so.
    """

    if name != "app":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    instance = create_app()
    globals()["app"] = instance
    return instance
