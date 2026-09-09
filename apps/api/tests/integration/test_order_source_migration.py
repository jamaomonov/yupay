"""Migration 0073 in both directions — the widened ``orders.source`` CHECK.

Two things here have never run anywhere else and would first be exercised on a
real database, by hand, under pressure:

* the **constraint name**. ``core.db.NAMING_CONVENTION`` re-templates even an
  explicitly named ``CheckConstraint``, so what 0046 shipped is
  ``ck_orders_ck_orders_source_known`` and not the name it wrote. 0073 addresses
  it with the same bare full name, which templates back into the live one — a
  claim, until something drops and re-adds it for real.
* the **downgrade refusal**. Narrowing the vocabulary back while merchant
  orders exist cannot succeed, and the migration says so in words rather than
  leaving Postgres to answer with a constraint name. A ``raise`` nothing has
  executed is a message nobody has read.
* the **backfill**. Existing merchant orders are relabelled from ``unknown``,
  and the rule has to hold in both directions: it must move a merchant row and
  must not touch a retail one.

The upgrade is already proven by every other integration test — the whole suite
builds its schema by running to head — so what is left is the reverse.

``db_engine`` is requested for fixture ordering: it starts the session-scoped
testcontainer, applies every migration, and TRUNCATEs before this body runs, so
``orders`` is empty when the downgrade below is attempted. Each xdist worker
owns its own Postgres (see ``.github/workflows/ci.yml``), so downgrading here
disturbs nobody else — and the ``finally`` puts this one back at head whatever
happens, because a worker left at 0072 would fail every later merchant test
with an error pointing anywhere but here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from yupay.core import config as cfg
from yupay.core.ids import new_id

pytestmark = pytest.mark.asyncio

_PREVIOUS = "0072_order_items_merchant_quote"


def _alembic_config() -> Config:
    """Point Alembic at the running test database (mirrors ``conftest``)."""
    api_dir = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(api_dir / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(api_dir / "migrations"))
    alembic_cfg.set_main_option("sqlalchemy.url", cfg.get_settings().database_url)
    return alembic_cfg


async def _insert_merchant() -> str:
    """One merchant account — ``id`` and ``title`` are the only required columns."""
    merchant_id = new_id()
    engine = create_async_engine(cfg.get_settings().database_url, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO merchants (id, title) VALUES (:id, :title)"),
                {"id": merchant_id, "title": f"src-mig-{merchant_id[:8]}"},
            )
    finally:
        await engine.dispose()
    return merchant_id


async def _insert_order(source: str, *, merchant_id: str | None = None) -> str:
    """One guest order carrying ``source``, inserted with raw SQL.

    Raw rather than the ORM for the same reason 0068's migration test uses it:
    the mapped class is the schema at head, and this test is about a schema
    that is deliberately not at head. Guest arm because it satisfies
    ``ck_orders_actor_exclusive`` with one column.
    """
    order_id = new_id()
    # ``ck_orders_actor_exclusive`` wants exactly one arm, so the guest email is
    # present only when no merchant is.
    email = None if merchant_id else f"src-mig-{order_id[:8]}@example.test"
    engine = create_async_engine(cfg.get_settings().database_url, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO orders (id, guest_email, merchant_id, status, currency, "
                    "total_usd, total_charged, expires_at, source) VALUES (:id, :email, "
                    ":merchant_id, 'pending_payment', 'USD', 1, 1, now() + interval '1 hour', "
                    ":source)"
                ),
                {
                    "id": order_id,
                    "email": email,
                    "merchant_id": merchant_id,
                    "source": source,
                },
            )
    finally:
        await engine.dispose()
    return order_id


async def _source_of(order_id: str) -> str:
    engine = create_async_engine(cfg.get_settings().database_url, future=True)
    try:
        async with engine.connect() as conn:
            return str(
                (
                    await conn.execute(
                        text("SELECT source FROM orders WHERE id = :id"), {"id": order_id}
                    )
                ).scalar_one()
            )
    finally:
        await engine.dispose()


async def _cleanup() -> None:
    """Every row these tests create, gone — whether they passed or not.

    Left behind, a merchant order with an unfamiliar id is exactly the kind of
    state that makes a later test in the same worker fail somewhere else.
    """
    engine = create_async_engine(cfg.get_settings().database_url, future=True)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM orders WHERE guest_email LIKE 'src-mig-%' "
                    "OR merchant_id IN (SELECT id FROM merchants WHERE title LIKE 'src-mig-%')"
                )
            )
            await conn.execute(text("DELETE FROM merchants WHERE title LIKE 'src-mig-%'"))
    finally:
        await engine.dispose()


async def test_the_check_accepts_the_b2b_values_and_still_refuses_nonsense(
    db_engine: Any,
) -> None:
    """The live constraint, not the ORM's copy of it.

    ``test_orders_source.py`` pins the model's predicate; this pins the one
    Postgres is actually enforcing, which is the one an INSERT meets.
    """
    await _insert_order("merchant_api")
    await _cleanup()

    # Short enough to reach the CHECK: ``source`` is ``varchar(16)``, so a
    # longer value is refused by the type before the constraint is consulted
    # (both new values fit — ``merchant_panel`` is the longer, at 14).
    with pytest.raises(Exception, match="ck_orders_ck_orders_source_known"):
        await _insert_order("partners")


async def test_downgrading_refuses_while_a_merchant_order_exists(db_engine: Any) -> None:
    """The refusal, in the words the operator would actually see."""
    alembic_cfg = _alembic_config()
    await _insert_order("merchant_api")
    try:
        with pytest.raises(RuntimeError, match="Refusing to downgrade 0073"):
            await asyncio.to_thread(command.downgrade, alembic_cfg, _PREVIOUS)
    finally:
        await _cleanup()
        # The refusal aborts before any DDL, so the schema should still be at
        # head — but re-upgrading is cheap and a no-op, and the alternative is
        # a worker silently left one revision back.
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")


async def test_downgrading_succeeds_once_nothing_uses_the_new_values(db_engine: Any) -> None:
    """And re-upgrading restores the widened set — both DDL paths, by name."""
    alembic_cfg = _alembic_config()
    try:
        await asyncio.to_thread(command.downgrade, alembic_cfg, _PREVIOUS)
        with pytest.raises(Exception, match="ck_orders_ck_orders_source_known"):
            await _insert_order("merchant_api")
    finally:
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    await _insert_order("merchant_api")
    await _cleanup()


async def test_the_backfill_relabels_merchant_orders_and_leaves_retail_alone(
    db_engine: Any,
) -> None:
    """0046 refused to guess ``web``; this one is not guessing.

    ``merchant_id IS NOT NULL`` has exactly one writer — ``POST
    /merchant/v1/orders`` — so the surface of an existing merchant order is
    known rather than inferred. The retail row beside it is the other half of
    the claim: an order that genuinely never said where it came from must stay
    ``unknown``, or the backfill has stopped being evidence.
    """
    alembic_cfg = _alembic_config()
    try:
        await asyncio.to_thread(command.downgrade, alembic_cfg, _PREVIOUS)
        merchant_id = await _insert_merchant()
        b2b = await _insert_order("unknown", merchant_id=merchant_id)
        retail = await _insert_order("unknown")
    finally:
        await asyncio.to_thread(command.upgrade, alembic_cfg, "head")

    try:
        assert await _source_of(b2b) == "merchant_api"
        assert await _source_of(retail) == "unknown"
    finally:
        await _cleanup()
