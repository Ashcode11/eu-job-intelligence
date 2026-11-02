"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from backend.api.routes import applications, candidate, discovery, health, jobs, monitoring
from backend.middleware import RequestContextMiddleware
from backend.security import rate_limit, require_api_key
from common.config import Settings, get_settings
from common.logging import configure_logging, get_logger
from database.session import create_engine, create_session_factory

log = get_logger(__name__)

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None, engine: AsyncEngine | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db_engine = engine or create_engine(settings)
        app.state.engine = db_engine
        app.state.session_factory = create_session_factory(db_engine)
        app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        if not settings.api_keys:
            log.warning("no_api_keys_configured", detail="all /api routes will return 401")
        log.info("startup", environment=settings.environment)
        try:
            yield
        finally:
            await app.state.redis.aclose()
            if engine is None:
                await db_engine.dispose()
            log.info("shutdown")

    app = FastAPI(
        title="EU Job Intelligence API",
        version="0.1.0",
        description=(
            "Self-hosted multi-agent European job search platform. "
            "All `/api/v1` endpoints require an `X-API-Key` header."
        ),
        lifespan=lifespan,
    )
    # Routes resolve settings through DI, so an explicitly passed Settings wins everywhere.
    app.dependency_overrides[get_settings] = lambda: settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["X-API-Key", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Echoing the submitted input back could leak secrets or personal data into logs.
        errors = [
            {k: v for k, v in e.items() if k not in ("input", "ctx", "url")} for e in exc.errors()
        ]
        return JSONResponse({"detail": errors}, status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return JSONResponse(
            {
                "detail": "Internal server error",
                "request_id": getattr(request.state, "request_id", None),
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    app.include_router(health.router)

    api = APIRouter(prefix=API_PREFIX, dependencies=[Depends(require_api_key), Depends(rate_limit)])
    for module in (candidate, jobs, applications, monitoring, discovery):
        api.include_router(module.router)
    app.include_router(api)
    return app


app = create_app()
