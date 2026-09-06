"""Composition root for the FastAPI app.

Each module that exposes HTTP routes provides a router; we mount them all here, under
``/api/v1``. Webhook routes are mounted under ``/webhooks/...`` separately.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from yupay.api.v1 import router as v1_router
from yupay.core.client_ip import client_ip as _client_ip
from yupay.core.config import Settings, get_settings
from yupay.core.db import dispose_engine
from yupay.core.errors import AppError, app_error_handler
from yupay.core.logging import configure_logging, get_logger
from yupay.core.redis import close_redis
from yupay.modules.fulfillment.suppliers.g2b_client import close_g2b_pool

#: Latency histogram bounds, in seconds. Dense below 250ms because most
#: traffic is fast (a catalog read is tens of milliseconds), and reaching 10s
#: because the supplier-touching endpoints genuinely go there — that upper
#: range is the part that has to be visible during an incident.
_LATENCY_BUCKETS = (0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


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
        # Bucket by route, not by URL. slowapi's default is ``"url"``, which
        # gives ``/orders/aaa`` and ``/orders/bbb`` separate budgets — so every
        # route carrying a path parameter was effectively unlimited (a caller
        # sweeping distinct ids never tripped anything), while the whole load
        # fell on the fixed-path endpoints every session touches: auth, the
        # catalog lists, the provider webhooks. That is the opposite of what
        # ADR-0028 describes. It also made key cardinality ``IPs x distinct
        # URLs``, and MemoryStorage sweeps every live key on a timer — so a
        # surge inflated the limiter into a load source of its own.
        key_style="endpoint",
    )


def _exempt_provider_callbacks(limiter: Limiter) -> None:
    """Take every acquirer and supplier callback out of the per-IP limiter.

    A 429 here costs money rather than buying safety. G2B fires each callback
    once with a single retry, so a throttled one is a delivery notification
    lost for good and the order sits at ``fulfilling`` until a reconcile sweep
    finds it. Payme reads a 429 as a transport failure and retries, which
    produces more 429s — and its whole documented source range is sixteen
    addresses sharing one bucket, four calls per order.

    Nothing is weakened by this: each of these routes authenticates the caller
    itself (JSON-RPC Basic auth, an MD5 signature, a path secret), and Payme is
    additionally IP-restricted at Caddy. The per-IP limit was never the control
    protecting them.

    Registered here, as a list, rather than as ``@limiter.exempt`` decorators
    spread over four modules: the limiter is built per app instance, the routes
    are declared at import time, and a security-relevant exemption is easier to
    audit when every entry sits in one place. ``exempt()`` keys off
    ``module.name``, which is what the middleware resolves per request.
    """
    from yupay.api.webhooks.g2b import receive_g2b_webhook
    from yupay.modules.click.routes import click_complete, click_prepare
    from yupay.modules.payme.routes import payme_merchant
    from yupay.modules.uzum.routes import (
        uzum_check,
        uzum_confirm,
        uzum_create,
        uzum_reverse,
        uzum_status,
    )

    for endpoint in (
        receive_g2b_webhook,
        payme_merchant,
        uzum_check,
        uzum_create,
        uzum_confirm,
        uzum_reverse,
        uzum_status,
        click_prepare,
        click_complete,
    ):
        # slowapi ships no types for this decorator; the return value is a
        # wrapper we discard — the side effect on the exempt set is the point.
        limiter.exempt(endpoint)  # type: ignore[no-untyped-call]


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
    (
        "INVENTORY_ENC_KEY",
        "inventory_enc_key",
        "at-rest encryption raises on first use in prod: no voucher code can be "
        "stored or read, and no merchant API key can be issued or verified "
        "(core.crypto derives a per-purpose key from this one input)",
    ),
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
        await close_g2b_pool()
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

    limiter = _build_limiter(settings)
    _exempt_provider_callbacks(limiter)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

    # Registered AFTER SlowAPIMiddleware on purpose. ``add_middleware``
    # prepends, so the last registration is the OUTERMOST layer — and CORS has
    # to be outermost because the limiter *short-circuits*: it returns its 429
    # without calling the rest of the stack. With CORS inside, that 429 reached
    # the browser bare, the browser blocked it, and ``fetch`` rejected as a
    # network error — so the client could not tell throttling from an outage
    # and its default retry fired three more times, multiplying exactly the
    # traffic that was already over the line.
    # ``["*"]`` plus credentials is rejected by browsers; route through
    # ``allow_origin_regex`` so the actual Origin is echoed back while still
    # allowing cookies / Authorization headers. Useful for ngrok / cloudflared
    # tunnels in dev.
    #
    # This branch must never activate in prod: reflecting every Origin with
    # credentials enabled is exactly the CORS misconfiguration that lets any
    # third-party site ride a victim's session. If an operator sets
    # ``CORS_ALLOW_ORIGINS=*`` in prod anyway, warn and fall back to the
    # explicit-origins branch below — with the literal ``"*"`` entry stripped
    # first, since passing it straight through as ``allow_origins=["*"]`` makes
    # Starlette set ``allow_all_origins`` just the same (see
    # ``CORSMiddleware.__init__``), which would silently reopen the same hole.
    if "*" in settings.cors_allow_origins and not settings.is_prod:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=".*",
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    else:
        if "*" in settings.cors_allow_origins:
            get_logger("yupay.bootstrap").warning(
                "cors_wildcard_ignored_in_prod",
                hint="CORS_ALLOW_ORIGINS=* is dev-only (reflects any Origin with "
                "credentials); set an explicit origin list for prod. Falling back "
                "to the explicit-origins list with '*' stripped, which allows no "
                "cross-origin browser requests until it is configured.",
            )
        origins = [origin for origin in settings.cors_allow_origins if origin != "*"]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

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

    # Explicit buckets. The library's per-handler default is (0.1, 0.5, 1),
    # which makes `histogram_quantile` unable to return anything above 1.0 —
    # the top finite bound is the ceiling. On production that showed up as
    # several handlers reporting a p95 of exactly "1000ms" (meaning "slower
    # than a second, unmeasurable"; `check-player` alone averages 1.69s), and
    # as the `ApiHighLatency` rule being dead code: it fires above 1.5s, which
    # the metric could never report. The series cost is handlers x buckets,
    # which is nothing at this size.
    Instrumentator().add(metrics.default(latency_lowr_buckets=_LATENCY_BUCKETS)).instrument(
        app
    ).expose(app, endpoint="/metrics", include_in_schema=False)

    return app
