"""Orders' third actor arm: ``merchant_id`` (migration 0066).

An order belongs to exactly one actor — a registered user, a guest email, or
(new) a B2B merchant. The exclusivity lives in the ``ck_orders_actor_exclusive``
CHECK, and these tests drive it through the *live* schema the migrations
produce, not just ORM metadata: the ``NAMING_CONVENTION`` re-templates
explicitly named CheckConstraints (see ``yupay.core.db``), so the name the ORM
reports and the name Postgres holds have already diverged once
(``ck_orders_ck_orders_actor_exclusive`` shipped in 0006). The pg_constraint
test here pins the repaired reality.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.merchants.models import Merchant
from yupay.modules.orders.models import Order
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _make_merchant(db: AsyncSession) -> str:
    """Insert a merchant row and return its id."""
    merchant_id = str(uuid.uuid4())
    db.add(Merchant(id=merchant_id, title=f"Reseller {merchant_id[:8]}"))
    await db.flush()
    return merchant_id


async def _make_user(db: AsyncSession) -> str:
    """Insert a buyer row and return its id."""
    user_id = str(uuid.uuid4())
    db.add(
        User(
            id=user_id,
            email=f"u-{user_id[:8]}@example.com",
            locale="ru",
            display_currency="USD",
            roles=[],
        )
    )
    await db.flush()
    return user_id


def _order(**actor_columns: str | None) -> Order:
    """Build an order with the given actor columns and neutral money fields."""
    return Order(
        id=str(uuid.uuid4()),
        status="pending_payment",
        currency="USD",
        total_usd=Decimal("10.00"),
        total_charged=Decimal("10.00"),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
        **actor_columns,
    )


async def test_a_merchant_order_needs_no_user_and_no_guest_email(
    db_session: AsyncSession,
) -> None:
    """An order with only ``merchant_id`` set satisfies the actor CHECK."""
    merchant_id = await _make_merchant(db_session)
    db_session.add(_order(merchant_id=merchant_id, user_id=None, guest_email=None))
    await db_session.commit()


@pytest.mark.parametrize("retail_arm", ["user_id", "guest_email"])
async def test_two_actors_still_rejected(db_session: AsyncSession, retail_arm: str) -> None:
    """``merchant_id`` combined with either retail arm violates the actor CHECK."""
    merchant_id = await _make_merchant(db_session)
    retail: dict[str, str | None] = (
        {"user_id": await _make_user(db_session), "guest_email": None}
        if retail_arm == "user_id"
        else {"user_id": None, "guest_email": "guest@example.com"}
    )
    db_session.add(_order(merchant_id=merchant_id, **retail))
    with pytest.raises(IntegrityError, match="ck_orders_actor_exclusive"):
        await db_session.commit()


async def test_zero_actors_still_rejected(db_session: AsyncSession) -> None:
    """An order with no actor at all violates the actor CHECK."""
    db_session.add(_order(merchant_id=None, user_id=None, guest_email=None))
    with pytest.raises(IntegrityError, match="ck_orders_actor_exclusive"):
        await db_session.commit()


async def test_merchant_with_orders_cannot_be_deleted(db_session: AsyncSession) -> None:
    """The FK is ON DELETE RESTRICT: merchant orders are financial history.

    A merchant that has traded gets frozen (``status='frozen'``), never
    deleted — deleting the row must fail while orders reference it.
    """
    merchant_id = await _make_merchant(db_session)
    db_session.add(_order(merchant_id=merchant_id, user_id=None, guest_email=None))
    await db_session.commit()

    delete = text("DELETE FROM merchants WHERE id = :mid")
    with pytest.raises(IntegrityError, match="fk_orders_merchant_id_merchants"):
        await db_session.execute(delete, {"mid": merchant_id})


async def test_actor_check_lives_under_its_clean_name(db_session: AsyncSession) -> None:
    """Pin the live constraint name in pg_constraint, not ORM metadata.

    The ``NAMING_CONVENTION`` re-templates explicitly named CheckConstraints,
    which is how 0006 shipped ``ck_orders_ck_orders_actor_exclusive`` to every
    real database. Migration 0066 drops that name and re-adds the CHECK via the
    bare-suffix trick so it finally lands as ``ck_orders_actor_exclusive``.
    Only the live catalog can prove the repair happened — the ORM's metadata
    reported the clean name all along.
    """
    rows = await db_session.execute(
        text(
            "SELECT conname FROM pg_constraint"
            " WHERE conrelid = 'orders'::regclass AND contype = 'c'"
        )
    )
    names = {row[0] for row in rows}
    assert "ck_orders_actor_exclusive" in names
    assert "ck_orders_ck_orders_actor_exclusive" not in names


async def test_merchant_order_partial_index_exists(db_session: AsyncSession) -> None:
    """``ix_orders_merchant_created`` mirrors ``ix_orders_user_created``."""
    rows = await db_session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'orders'")
    )
    by_name = {name: definition for name, definition in rows}
    assert "ix_orders_merchant_created" in by_name
    definition = by_name["ix_orders_merchant_created"]
    assert "WHERE (merchant_id IS NOT NULL)" in definition
    # The mirror must be exact: newest-first, like ``ix_orders_user_created``.
    assert "created_at DESC" in definition
