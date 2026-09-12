"""Integration-test fixtures.

A session-scoped Postgres testcontainer is started once per test session. The Alembic
migrations are applied against it. Each test gets a clean schema via TRUNCATE — much
faster than rebuilding the container.
"""

from __future__ import annotations

import os

# Ryuk (testcontainers' GC sidecar) is finicky on Docker Desktop; we don't need it for
# unit-shaped integration tests. Disable before importing the testcontainers package.
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.postgres import PostgresContainer
from yupay.core import config as cfg


@pytest.fixture(scope="session")
def _pg_container() -> Iterator[PostgresContainer]:
    container = PostgresContainer(image="postgres:16-alpine", driver=None).with_bind_ports(
        5432, None
    )
    container.start()
    try:
        yield container
    finally:
        container.stop()


def _make_async_url(container: PostgresContainer) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    user = container.username
    password = container.password
    db = container.dbname
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"


@pytest.fixture(scope="session", autouse=True)
def _apply_migrations(_pg_container: PostgresContainer, worker_id: str) -> None:
    """Point Settings + Alembic at the container and run migrations once."""
    url = _make_async_url(_pg_container)
    os.environ["DATABASE_URL"] = url
    # Point at the dev Redis exposed by docker-compose (the `.env` default uses the
    # docker-internal hostname which is unreachable from the host). Tests that need
    # full isolation use `fakeredis` at the call site; the rest hit this real instance.
    #
    # Redis itself isn't per-worker like the Postgres container above — it's one
    # shared instance (GH Actions `services:` / local docker-compose) — so under
    # pytest-xdist every worker would otherwise share one DB and
    # `_reset_realtime_redis` below (autouse, runs before every test) would
    # `flushdb()` another worker's in-flight test out from under it. `worker_id` is
    # pytest-xdist's built-in fixture ("master" outside xdist, "gw0"/"gw1"/... under
    # it) — give each worker its own logical Redis DB instead.
    #
    # DB 0 is deliberately excluded, because it is not free: the dev stack itself
    # runs on `redis://redis:6379/0` (docker-compose.yml), and locally that is the
    # very instance these tests connect to. With `gw0` on DB 0, the autouse
    # `flushdb()` wiped the running dev stack's Redis before every test in that
    # worker, and the dev worker/scheduler/bot wrote into the DB `gw0` was asserting
    # against. Both directions were silent. Workers now map to 1-15.
    db_index = (int(worker_id[2:]) % 15) + 1 if worker_id.startswith("gw") else 1
    os.environ["REDIS_URL"] = f"redis://localhost:6379/{db_index}"
    cfg.get_settings.cache_clear()

    api_dir = Path(__file__).resolve().parents[2]
    ini = api_dir / "alembic.ini"
    alembic_cfg = Config(str(ini))
    alembic_cfg.set_main_option("script_location", str(api_dir / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_cfg, "head")


@pytest.fixture(autouse=True)
async def _reset_realtime_redis() -> AsyncIterator[None]:
    """Reset the ``get_redis()`` singleton around every integration test.

    Order-status transitions (``payments``/``fulfillment``/``orders`` services)
    publish to Redis via ``realtime.api.publish_order_event`` — not just the
    handful of WS-specific tests that already reset this through
    ``integration_client``. Any test driving those services directly against
    ``db_session`` can now reach ``get_redis()`` too. Each pytest-asyncio test
    runs on its own event loop; a client cached from a previous test would be
    bound to a closed loop and blow up with "Future attached to a different
    loop" / "Event loop is closed" the moment a later test publishes. Resetting
    here (in addition to ``integration_client``'s own reset, which is now
    redundant but harmless) makes every test start from — and leave — a clean
    singleton regardless of which fixtures it requests.
    """
    import contextlib

    from yupay.core import redis as core_redis

    core_redis._client = None  # type: ignore[attr-defined]
    # Flush leftover Redis DATA (the singleton reset only drops the client object).
    # Per-IP guard counters, single-use token markers, and revocation blocklists
    # would otherwise accumulate across the whole run from the shared test-client
    # IP — e.g. the /register guard would trip mid-suite once enough tests have
    # registered. Flushing per test keeps within-test rate-limit loops working
    # (they still accumulate inside one test) while isolating tests from each other.
    # Close the flush client immediately: ``integration_client`` resets the
    # singleton on its own setup, which would otherwise orphan this client's
    # connection — a leak that exhausts the pool and hangs the run mid-suite.
    with contextlib.suppress(Exception):
        await core_redis.get_redis().flushdb()
        await core_redis.close_redis()
    yield
    await core_redis.close_redis()


@pytest.fixture
async def db_engine():
    """A fresh async engine per test. Truncates tables before each test."""
    settings = cfg.get_settings()
    engine = create_async_engine(settings.database_url, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "TRUNCATE TABLE "
                    "idempotent_responses, "
                    "steam_gift_settings, "
                    "review_reports, reviews, brand_rating_stats, "
                    "broadcast_recipients, broadcasts, "
                    "promo_redemptions, promo_codes, "
                    # Listed explicitly rather than left to CASCADE. They would
                    # be reached today through affiliate_partners.user_id, but
                    # that column is nullable and exists only for the
                    # own-code check — drop it one day and partner rows would
                    # quietly start surviving between tests.
                    "affiliate_sessions, affiliate_payouts, affiliate_commissions, "
                    "affiliate_attributions, affiliate_codes, affiliate_partners, "
                    "wallet_postings, wallet_transactions, wallet_accounts, "
                    "inventory_codes, inventory_uploads, sku_sourcing_rules, "
                    "sku_supplier_mapping, supplier_catalog_cache, supplier_price_history, "
                    "deliveries, fulfillment_attempts, fulfillment_tasks, "
                    "payme_transactions, uzum_transactions, click_transactions, "
                    "payment_webhooks, payment_attempts, payments, payment_provider_states, "
                    "order_events, order_items, orders, "
                    # After orders: orders.merchant_id is ON DELETE RESTRICT,
                    # but TRUNCATE ... CASCADE in one statement handles it; the
                    # rows must go regardless or merchants leak across tests.
                    "merchant_webhook_deliveries, merchant_webhooks, "
                    "merchant_api_keys, merchant_users, merchants, "
                    "sku_prices, skus, product_translations, products, "
                    "blog_indexnow_pings, blog_post_likes, blog_post_views, "
                    "blog_post_faqs, blog_post_brands, blog_post_translations, blog_posts, "
                    "brand_translations, brands, "
                    "category_translations, categories, "
                    "fx_snapshots, fx_rates, "
                    "auth_sessions, telegram_links, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db_session(db_engine) -> AsyncIterator[AsyncSession]:
    """A session bound to the truncated engine."""
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session


@pytest.fixture
async def integration_client(db_engine) -> AsyncIterator[AsyncClient]:
    """An ASGI HTTP client wired to a fresh FastAPI app + truncated DB."""
    from yupay.bootstrap import create_app
    from yupay.core import db as core_db
    from yupay.core import redis as core_redis

    # Swap the global engine so the app's session dependency uses the test engine.
    factory = async_sessionmaker(bind=db_engine, expire_on_commit=False)
    core_db._engine = db_engine  # type: ignore[attr-defined]
    core_db._session_factory = factory  # type: ignore[attr-defined]

    # Reset the Redis singleton so it is re-created on the current event loop.
    # Each pytest-asyncio function test runs in its own loop; a cached client from
    # a previous test would be bound to a closed loop, causing "Future attached to
    # a different loop" errors for the second Redis-using test in a session.
    core_redis._client = None  # type: ignore[attr-defined]

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    core_db._engine = None  # type: ignore[attr-defined]
    core_db._session_factory = None  # type: ignore[attr-defined]
    # Close the Redis client so its connection pool doesn't linger on this loop.
    await core_redis.close_redis()
