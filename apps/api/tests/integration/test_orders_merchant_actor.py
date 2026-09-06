"""Orders' third actor arm: ``merchant_id`` (migrations 0066 and 0069).

An order belongs to exactly one actor — a registered user, a guest email, or
(new) a B2B merchant. The exclusivity lives in the ``ck_orders_actor_exclusive``
CHECK, and these tests drive it through the *live* schema the migrations
produce, not just ORM metadata: the ``NAMING_CONVENTION`` re-templates
explicitly named CheckConstraints (see ``yupay.core.db``), so the name the ORM
reports and the name Postgres holds have already diverged once
(``ck_orders_ck_orders_actor_exclusive`` shipped in 0006). The pg_constraint
test here pins the repaired reality.

The second half of the file covers the *service* seam 0066's column was cut
for: ``orders.service.Actor`` grew the same third arm, so a merchant order can
actually be created, replayed per merchant (``uq_orders_idem_merchant``,
migration 0069) and read back by its owner and nobody else.
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


async def _seed_sku(db: AsyncSession, *, price_usd: str = "10.00") -> str:
    """Seed a minimal buyable category → brand → product → SKU chain."""
    from yupay.core.ids import new_id
    from yupay.modules.catalog.models import (
        Brand,
        BrandTranslation,
        Category,
        CategoryTranslation,
        Product,
        ProductTranslation,
        Sku,
    )

    cat = Category(id=new_id(), slug=f"c-{new_id()[:8]}", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Игры")]
    db.add(cat)
    await db.flush()

    brand = Brand(
        id=new_id(), slug=f"b-{new_id()[:8]}", category_id=cat.id, sort_order=0, active=True
    )
    brand.translations = [BrandTranslation(locale="ru", name="B")]
    db.add(brand)
    await db.flush()

    product = Product(id=new_id(), slug=f"p-{new_id()[:8]}", brand_id=brand.id, kind="top_up")
    product.translations = [ProductTranslation(locale="ru", name="P")]
    db.add(product)
    await db.flush()

    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code=f"s-{new_id()[:8]}",
        price_usd=Decimal(price_usd),
        cost_usdt=Decimal("8.00"),
    )
    db.add(sku)
    await db.flush()
    return sku.id


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


async def test_a_merchant_actor_can_place_an_order(db_session: AsyncSession) -> None:
    """The seam this task opens: ``create_order`` accepts a merchant actor.

    Before the widening, ``Actor`` had no merchant arm at all, so no merchant
    order could be created through the service at all — only by hand-writing
    the row, as the CHECK tests above do.
    """
    from yupay.core.ids import new_id
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    merchant_id = await _make_merchant(db_session)
    sku_id = await _seed_sku(db_session)

    order = await create_order(
        db_session,
        OrderCreate(currency="USD", items=[OrderItemIn(sku_id=sku_id, qty=1)]),
        actor=Actor(user_id=None, email=None, merchant_id=merchant_id),
        idempotency_key=new_id(),
    )

    assert order.merchant_id == merchant_id
    assert order.user_id is None
    assert order.guest_email is None
    # Audit trail names the merchant, not a hashed guest pseudonym.
    assert [e.actor for e in order.events] == [f"merchant:{merchant_id}"]


async def test_same_merchant_key_returns_the_same_order(db_session: AsyncSession) -> None:
    """A merchant's retry replays its first order instead of buying twice."""
    from yupay.core.ids import new_id
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    merchant_id = await _make_merchant(db_session)
    sku_id = await _seed_sku(db_session)
    actor = Actor(user_id=None, email=None, merchant_id=merchant_id)
    key = new_id()
    body = OrderCreate(currency="USD", items=[OrderItemIn(sku_id=sku_id, qty=1)])

    first = await create_order(db_session, body, actor=actor, idempotency_key=key)
    second = await create_order(db_session, body, actor=actor, idempotency_key=key)

    assert first.id == second.id
    count = await db_session.scalar(
        text("SELECT count(*) FROM orders WHERE merchant_id = :mid"), {"mid": merchant_id}
    )
    assert count == 1


async def test_two_merchants_may_share_a_key(db_session: AsyncSession) -> None:
    """Idempotency is scoped per merchant, exactly as it is per user and per guest.

    Merchants pick their own ``merchant_order_id``s and cannot see each other's,
    so a collision between two resellers is expected traffic, not a replay.
    """
    from yupay.core.ids import new_id
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    first_merchant = await _make_merchant(db_session)
    second_merchant = await _make_merchant(db_session)
    sku_id = await _seed_sku(db_session)
    key = new_id()
    body = OrderCreate(currency="USD", items=[OrderItemIn(sku_id=sku_id, qty=1)])

    one = await create_order(
        db_session,
        body,
        actor=Actor(user_id=None, email=None, merchant_id=first_merchant),
        idempotency_key=key,
    )
    two = await create_order(
        db_session,
        body,
        actor=Actor(user_id=None, email=None, merchant_id=second_merchant),
        idempotency_key=key,
    )

    assert one.id != two.id
    assert one.merchant_id == first_merchant
    assert two.merchant_id == second_merchant


async def test_a_merchant_key_never_replays_a_retail_order(db_session: AsyncSession) -> None:
    """Cross-arm proof: a user's key and a merchant's key are separate namespaces."""
    from yupay.core.ids import new_id
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import Actor, create_order

    merchant_id = await _make_merchant(db_session)
    user_id = await _make_user(db_session)
    sku_id = await _seed_sku(db_session)
    key = new_id()
    body = OrderCreate(currency="USD", items=[OrderItemIn(sku_id=sku_id, qty=1)])

    retail = await create_order(
        db_session, body, actor=Actor(user_id=user_id, email=None), idempotency_key=key
    )
    b2b = await create_order(
        db_session,
        body,
        actor=Actor(user_id=None, email=None, merchant_id=merchant_id),
        idempotency_key=key,
    )

    assert retail.id != b2b.id
    assert retail.merchant_id is None
    assert b2b.user_id is None


async def test_a_merchant_reads_only_its_own_orders(db_session: AsyncSession) -> None:
    """Owner scoping follows the merchant arm too — no cross-reseller reads."""
    from yupay.core.errors import NotFoundError
    from yupay.core.ids import new_id
    from yupay.modules.orders.schemas import OrderCreate, OrderItemIn
    from yupay.modules.orders.service import (
        Actor,
        create_order,
        get_order_for_actor,
        list_orders_for_actor,
    )

    mine = await _make_merchant(db_session)
    theirs = await _make_merchant(db_session)
    sku_id = await _seed_sku(db_session)
    body = OrderCreate(currency="USD", items=[OrderItemIn(sku_id=sku_id, qty=1)])

    order = await create_order(
        db_session,
        body,
        actor=Actor(user_id=None, email=None, merchant_id=mine),
        idempotency_key=new_id(),
    )

    found = await get_order_for_actor(
        db_session, order.id, actor=Actor(user_id=None, email=None, merchant_id=mine)
    )
    assert found.id == order.id
    with pytest.raises(NotFoundError):
        await get_order_for_actor(
            db_session, order.id, actor=Actor(user_id=None, email=None, merchant_id=theirs)
        )

    assert [
        o.id
        for o in await list_orders_for_actor(
            db_session, actor=Actor(user_id=None, email=None, merchant_id=mine)
        )
    ] == [order.id]
    assert (
        await list_orders_for_actor(
            db_session, actor=Actor(user_id=None, email=None, merchant_id=theirs)
        )
        == []
    )


async def test_merchant_idempotency_index_exists(db_session: AsyncSession) -> None:
    """``uq_orders_idem_merchant`` mirrors the user and guest partial UNIQUEs.

    The race a merchant's ``merchant_order_id`` has to survive is two of its own
    requests landing at once; that must be resolved by the database, not by the
    read-then-write in ``_existing_idempotent_order``.
    """
    rows = await db_session.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'orders'")
    )
    by_name = {name: definition for name, definition in rows}
    assert "uq_orders_idem_merchant" in by_name
    definition = by_name["uq_orders_idem_merchant"]
    assert "CREATE UNIQUE INDEX" in definition
    assert "merchant_id, idempotency_key" in definition
    assert "WHERE ((merchant_id IS NOT NULL) AND (idempotency_key IS NOT NULL))" in definition


async def test_the_index_rejects_a_duplicate_merchant_key(db_session: AsyncSession) -> None:
    """Two rows, same merchant, same key — the database refuses the second."""
    from yupay.core.ids import new_id

    merchant_id = await _make_merchant(db_session)
    key = new_id()
    db_session.add(
        _order(merchant_id=merchant_id, user_id=None, guest_email=None, idempotency_key=key)
    )
    await db_session.commit()

    db_session.add(
        _order(merchant_id=merchant_id, user_id=None, guest_email=None, idempotency_key=key)
    )
    with pytest.raises(IntegrityError, match="uq_orders_idem_merchant"):
        await db_session.commit()


# ---- the sibling owner guards -------------------------------------------------
#
# Two route-level guards outside this module compare a *retail* actor against an
# order and, before the fix that ships with these tests, denied a merchant actor
# only by accident: both sides of their email comparison collapse to ``""``, the
# inequality is False, and the guard passes — for any order in the table, a
# signed-in user's included (their ``guest_email`` is NULL too). They are tested
# here rather than beside their own modules because the hazard is a property of
# the widened ``Actor``, not of payments or fulfilment.


async def test_the_payments_owner_guard_refuses_a_merchant_actor(
    db_session: AsyncSession,
) -> None:
    """A merchant actor gets 404 from a user's order, not a free pass."""
    # ``payments.routes`` imports ``yupay.api.v1.deps``, which the v1 package
    # __init__ imports back through ``payments.api`` — importing the route
    # module first hits that cycle mid-initialisation. Load the router package
    # first and the chain resolves the way the app loads it.
    import yupay.api.v1  # noqa: F401
    from fastapi import HTTPException
    from yupay.modules.orders.service import Actor
    from yupay.modules.payments.routes import _ensure_actor_owns_order

    merchant_id = await _make_merchant(db_session)
    user_id = await _make_user(db_session)
    someone_elses = _order(user_id=user_id, guest_email=None, merchant_id=None)
    db_session.add(someone_elses)
    await db_session.flush()

    with pytest.raises(HTTPException) as raised:
        await _ensure_actor_owns_order(
            db_session,
            actor=Actor(user_id=None, email=None, merchant_id=merchant_id),
            order_id=someone_elses.id,
        )
    assert raised.value.status_code == 404


async def test_the_fulfilment_owner_guard_refuses_a_merchant_actor(
    db_session: AsyncSession,
) -> None:
    """404 for a stranger's order **and** for the merchant's own.

    This is the magic-link path: it unlocks delivered codes to whoever bears a
    token bound to the address we mailed. A merchant has no mailed address — it
    reads its own orders over ``/merchant/v1`` via ``get_order_for_actor`` — so
    "its own order" is not an exception here, it is the second half of the rule.
    """
    # Same router-package cycle as the payments guard above.
    import yupay.api.v1  # noqa: F401
    from fastapi import HTTPException
    from yupay.modules.fulfillment.routes import _ensure_order_owner
    from yupay.modules.orders.service import Actor

    merchant_id = await _make_merchant(db_session)
    user_id = await _make_user(db_session)
    someone_elses = _order(user_id=user_id, guest_email=None, merchant_id=None)
    its_own = _order(user_id=None, guest_email=None, merchant_id=merchant_id)
    db_session.add_all([someone_elses, its_own])
    await db_session.flush()

    for order_id in (someone_elses.id, its_own.id):
        with pytest.raises(HTTPException) as raised:
            await _ensure_order_owner(
                db_session,
                actor=Actor(user_id=None, email=None, merchant_id=merchant_id),
                order_id=order_id,
            )
        assert raised.value.status_code == 404
