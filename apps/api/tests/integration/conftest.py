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
def _apply_migrations(_pg_container: PostgresContainer) -> None:
    """Point Settings + Alembic at the container and run migrations once."""
    url = _make_async_url(_pg_container)
    os.environ["DATABASE_URL"] = url
    # Point at the dev Redis exposed by docker-compose (the `.env` default uses the
    # docker-internal hostname which is unreachable from the host). Tests that need
    # full isolation use `fakeredis` at the call site; the rest hit this real instance.
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    cfg.get_settings.cache_clear()

    api_dir = Path(__file__).resolve().parents[2]
    ini = api_dir / "alembic.ini"
    alembic_cfg = Config(str(ini))
    alembic_cfg.set_main_option("script_location", str(api_dir / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(alembic_cfg, "head")


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
                    "wallet_postings, wallet_transactions, wallet_accounts, "
                    "inventory_codes, inventory_uploads, sku_sourcing_rules, "
                    "sku_supplier_mapping, supplier_catalog_cache, supplier_price_history, "
                    "deliveries, fulfillment_attempts, fulfillment_tasks, "
                    "payment_webhooks, payment_attempts, payments, "
                    "order_events, order_items, orders, "
                    "sku_prices, skus, product_translations, products, "
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
