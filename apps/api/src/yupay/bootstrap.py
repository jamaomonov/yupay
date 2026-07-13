"""Composition root for the FastAPI app.

Each module that exposes HTTP routes provides a router; we mount them all here, under
``/api/v1``. Webhook routes are mounted under ``/webhooks/...`` separately.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from yupay.api.v1 import router as v1_router
from yupay.core.config import Settings, get_settings
from yupay.core.db import dispose_engine
from yupay.core.errors import AppError, app_error_handler
from yupay.core.logging import configure_logging, get_logger
from yupay.core.redis import close_redis


def _client_ip(request: Request) -> str:
    """Rate-limit key: the client IP as seen by Caddy.

    In prod the API sits behind Caddy, which appends the real client to
    ``X-Forwarded-For`` — the direct peer is always the proxy, so the first
    entry is the customer. The API port is not exposed publicly (compose), so
    the header can't be spoofed around the proxy.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _build_limiter(settings: Settings) -> Limiter:
    """Global per-IP limiter (AGENTS.md §9).

    Storage is per-process memory, NOT Redis: ``limits``' Redis backend is
    synchronous and would block the event loop on every request. With a
    single-VPS deploy and a handful of uvicorn workers the per-process
    approximation (N workers ⇒ ≤ N× the nominal limit) is an acceptable
    outer circuit breaker; auth endpoints add their own Redis-backed
    ``ip_guard`` on top. See ADR-0028.
    """
    enabled = (
        settings.rate_limit_enabled
        if settings.rate_limit_enabled is not None
        else not settings.is_test
    )
    return Limiter(
        key_func=_client_ip,
        default_limits=[settings.rate_limit_default],
        storage_uri="memory://",
        enabled=enabled,
        headers_enabled=True,
    )


def _init_sentry(settings: Settings) -> None:
    """Initialise Sentry if a DSN is configured.

    Kept inline (not eager-imported) so dev environments without a DSN
    don't drag in the ~2 MB SDK + integrations. ``traces_sample_rate``
    comes from settings — usual prod default is ``0.1`` (10% transactions
    captured for tracing).
    """
    if not settings.sentry_dsn:
        return
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.starlette import StarletteIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.service_name,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,  # never ship PII to Sentry; AGENTS.md §9
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            StarletteIntegration(transaction_style="endpoint"),
        ],
    )


if TYPE_CHECKING:
    from collections.abc import AsyncIterator


# Settings that a production deploy is broken without, mapped to what silently
# stops working when they are empty. Not a completeness check — payment gateways
# and suppliers report ``available=false`` and degrade visibly, so they stay out.
_REQUIRED_IN_PROD: tuple[tuple[str, str, str], ...] = (
    (
        "TELEGRAM_BOT_TOKEN",
        "telegram_bot_token",
        "mini-app login: initData is HMAC-signed with the bot token, so "
        "/auth/telegram/webapp 401s for every user",
    ),
    ("AUTH_EMAIL_PEPPER", "auth_email_pepper", "guest JWTs hash emails with an empty pepper"),
    ("R2_ACCOUNT_ID", "r2_account_id", "media upload raises on the first presign"),
    ("R2_ACCESS_KEY_ID", "r2_access_key_id", "media upload raises on the first presign"),
    ("R2_SECRET_ACCESS_KEY", "r2_secret_access_key", "media upload raises on the first presign"),
)


def missing_prod_settings(settings: Settings) -> list[str]:
    """Return the env var names a prod deploy is missing.

    Empty outside prod: local and CI runs routinely have no third-party
    credentials, and nagging about it there trains people to ignore the warning.

    Args:
        settings: The resolved application settings.

    Returns:
        Env var names that are empty but required in production, in declaration
        order. Empty list when the environment is not prod, or nothing is missing.
    """
    if not settings.is_prod:
        return []
    return [
        env_name
        for env_name, field, _ in _REQUIRED_IN_PROD
        if not str(getattr(settings, field, "")).strip()
    ]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """App lifespan — wire startup and shutdown side effects."""
    configure_logging()
    logger = get_logger("yupay.bootstrap")
    settings = get_settings()
    logger.info("startup", environment=settings.environment)

    # Warn, don't raise: a stack has to be able to boot before its third-party
    # credentials exist, and refusing to start would take the storefront down
    # over a disabled integration. But it must not be silent — an empty bot token
    # breaks mini-app login for every user while every container stays "healthy",
    # and the usual cause is applying a secret with ``docker compose restart``,
    # which does not re-read env_file (use ``up -d``).
    missing = missing_prod_settings(settings)
    if missing:
        reasons = {name: why for name, _, why in _REQUIRED_IN_PROD if name in missing}
        logger.warning(
            "prod_config_incomplete",
            missing=missing,
            impact=reasons,
            hint="apply secrets with `docker compose up -d`, not `restart` — "
            "restart reuses the container and keeps the old env_file values",
        )

    try:
        yield
    finally:
        await close_redis()
        await dispose_engine()
        logger.info("shutdown")


def create_app() -> FastAPI:
    """Build a fresh FastAPI app with all routers, middleware, and exception handlers."""
    settings = get_settings()
    _init_sentry(settings)
    # NOTE: FastAPI 0.115+ serialises responses directly via Pydantic — no custom
    # response class needed. Explicit `ORJSONResponse` is deprecated.
    app = FastAPI(
        title="YuPay API",
        version="0.0.1",
        openapi_url="/openapi.json",
        docs_url="/docs" if not settings.is_prod else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # ``["*"]`` plus credentials is rejected by browsers; route through
    # ``allow_origin_regex`` so the actual Origin is echoed back while still
    # allowing cookies / Authorization headers. Useful for ngrok / cloudflared
    # tunnels in dev.
    if "*" in settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=".*",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

    limiter = _build_limiter(settings)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    @app.get("/healthz", tags=["meta"], summary="Liveness probe")
    @limiter.exempt  # type: ignore[untyped-decorator]  # slowapi ships no decorator types
    async def healthz() -> dict[str, str]:
        """Return ``{"status": "ok"}`` if the process is alive."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["meta"], summary="Readiness probe")
    @limiter.exempt  # type: ignore[untyped-decorator]  # slowapi ships no decorator types
    async def readyz() -> dict[str, str]:
        """Return ``{"status": "ready"}`` once all dependencies are reachable.

        At MVP this is a stub; later it will check DB, Redis, broker, and critical suppliers.
        """
        return {"status": "ready"}

    app.include_router(v1_router, prefix="/api/v1")

    Instrumentator().instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    return app
