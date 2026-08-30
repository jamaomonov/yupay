"""Integration tests for the rolling-sum/velocity window rules (ADR-0062).

Runs against real Postgres because the point being proven here is `_gather`'s
SQL — that an `OrderEvidence` IP correctly links otherwise-unrelated guest
orders into one identity — not the comparison logic in `_window_reason`,
which is fully covered (with fixed inputs, no database) by
`tests/unit/test_order_risk.py`.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
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
from yupay.modules.evidence.models import OrderEvidence
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.orders.risk import REASON_GEO_MISMATCH, REASON_ROLLING_SUM, review_reason
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _paid_guest_order(
    db: AsyncSession,
    *,
    guest_email: str,
    total_usd: str,
    paid_at_minutes_ago: int,
    ip: str,
) -> Order:
    """A minimal paid catalog order with an evidence row carrying its IP.

    No SKUs or order items: `_gather`'s Query A only joins `Order` and
    `OrderEvidence`, and its Query B (fulfilment-data targets) tolerates an
    order with no items — it simply contributes an empty target set.
    """
    moment = now()
    order = Order(
        id=new_id(),
        guest_email=guest_email,
        status="paid",
        currency="USD",
        total_usd=Decimal(total_usd),
        total_charged=Decimal(total_usd),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment - timedelta(minutes=paid_at_minutes_ago),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderEvidence(
            order_id=order.id,
            ip=ip,
            purge_after=moment + timedelta(days=180),
        )
    )
    await db.flush()
    return order


async def test_three_orders_sharing_one_ip_cross_the_rolling_sum_cap(
    db_session: AsyncSession,
) -> None:
    """Nothing but the IP links these three guests; $33 clears the $25 default cap."""
    shared_ip = "203.0.113.50"
    await _paid_guest_order(
        db_session,
        guest_email="a@example.test",
        total_usd="11",
        paid_at_minutes_ago=60,
        ip=shared_ip,
    )
    await _paid_guest_order(
        db_session,
        guest_email="b@example.test",
        total_usd="11",
        paid_at_minutes_ago=120,
        ip=shared_ip,
    )
    current = await _paid_guest_order(
        db_session,
        guest_email="c@example.test",
        total_usd="11",
        paid_at_minutes_ago=0,
        ip=shared_ip,
    )
    await db_session.commit()

    assert await review_reason(db_session, current) == REASON_ROLLING_SUM


async def test_a_control_order_on_a_different_ip_and_buyer_is_untouched(
    db_session: AsyncSession,
) -> None:
    """The same shared-IP pair exists, but the order under test shares nothing with it."""
    shared_ip = "203.0.113.51"
    await _paid_guest_order(
        db_session,
        guest_email="d@example.test",
        total_usd="11",
        paid_at_minutes_ago=60,
        ip=shared_ip,
    )
    await _paid_guest_order(
        db_session,
        guest_email="e@example.test",
        total_usd="11",
        paid_at_minutes_ago=120,
        ip=shared_ip,
    )
    control = await _paid_guest_order(
        db_session,
        guest_email="control@example.test",
        total_usd="11",
        paid_at_minutes_ago=0,
        ip="198.51.100.99",
    )
    await db_session.commit()

    assert await review_reason(db_session, control) is None


async def test_same_guest_email_in_different_case_links(db_session: AsyncSession) -> None:
    """`orders.guest_email` is CITEXT, so Query A's SQL predicate already
    matches these three case-insensitively — but `_window_reason`/
    `_shares_key` compare the fetched buyer strings with plain Python ``==``.
    Without `_gather` lowering both the current order's and each fetched
    sibling's buyer key, Postgres would find these rows and the Python
    comparison would then silently fail to link them. Different IPs so
    email-case is the only thing that can link these three — this is the
    regression test for that defensive `.lower()`, placed here rather than
    in the unit suite because the bug is specifically about the interaction
    between Postgres's case-insensitive match and Python's case-sensitive
    one, which only a real CITEXT column can exercise honestly.
    """
    await _paid_guest_order(
        db_session,
        guest_email="Case@Example.test",
        total_usd="11",
        paid_at_minutes_ago=60,
        ip="203.0.113.70",
    )
    await _paid_guest_order(
        db_session,
        guest_email="CASE@EXAMPLE.TEST",
        total_usd="11",
        paid_at_minutes_ago=120,
        ip="203.0.113.71",
    )
    current = await _paid_guest_order(
        db_session,
        guest_email="case@example.test",
        total_usd="11",
        paid_at_minutes_ago=0,
        ip="203.0.113.72",
    )
    await db_session.commit()

    assert await review_reason(db_session, current) == REASON_ROLLING_SUM


# ---------- geo mismatch (rule 5) ----------


@pytest.fixture
async def _liquid_sku(db_session: AsyncSession) -> str:
    """A SKU under brand slug ``roblox`` — in the default `risk_liquid_brands`.

    Real catalog rows, not a stub: the point of this integration test is
    `_gather`'s brand join (order_items -> skus -> products -> brands), which
    a `WindowOrder`-only unit test cannot exercise.
    """
    category = Category(
        id=new_id(),
        slug="risk-geo-cat",
        sort_order=1,
        active=True,
        translations=[CategoryTranslation(locale="ru", name="Geo")],
    )
    brand = Brand(
        id=new_id(),
        category_id=category.id,
        slug="roblox",
        sort_order=1,
        active=True,
        translations=[BrandTranslation(locale="ru", name="Roblox")],
    )
    product = Product(
        id=new_id(),
        brand_id=brand.id,
        slug="risk-geo-prod",
        kind="top_up",
        sort_order=1,
        active=True,
        required_fields=[],
        translations=[ProductTranslation(locale="ru", name="Geo Prod")],
    )
    sku = Sku(
        id=new_id(),
        product_id=product.id,
        sku_code="GEO-1",
        denomination="1",
        region="GLOBAL",
        price_usd=Decimal("5.00"),
        sort_order=1,
        active=True,
    )
    db_session.add_all([category, brand, product, sku])
    await db_session.commit()
    return sku.id


async def _paid_order_with_item(
    db: AsyncSession,
    *,
    sku_id: str,
    user_id: str | None,
    guest_email: str | None,
    timezone: str | None,
) -> Order:
    """A paid catalog order for one liquid-brand SKU, with an evidence row
    reporting `timezone` (or none, when `timezone` is ``None``)."""
    moment = now()
    order = Order(
        id=new_id(),
        user_id=user_id,
        guest_email=guest_email,
        status="paid",
        currency="USD",
        total_usd=Decimal("5"),
        total_charged=Decimal("5"),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment,
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=sku_id,
            qty=1,
            unit_price_usd=Decimal("5"),
        )
    )
    db.add(
        OrderEvidence(
            order_id=order.id,
            client_hints={"timezone": timezone} if timezone else {},
            purge_after=moment + timedelta(days=180),
        )
    )
    await db.flush()
    await db.commit()
    return order


async def test_a_guest_liquid_brand_foreign_tz_order_is_held(
    db_session: AsyncSession, _liquid_sku: str
) -> None:
    order = await _paid_order_with_item(
        db_session,
        sku_id=_liquid_sku,
        user_id=None,
        guest_email="geo@example.test",
        timezone="Europe/Kiev",
    )

    assert await review_reason(db_session, order) == REASON_GEO_MISMATCH


async def test_the_same_order_signed_in_is_fulfilled(
    db_session: AsyncSession, _liquid_sku: str
) -> None:
    """Same brand, same foreign timezone — only ``user_id`` differs."""
    user_id = new_id()
    db_session.add(User(id=user_id, email="signed-in@example.test"))
    await db_session.flush()
    order = await _paid_order_with_item(
        db_session,
        sku_id=_liquid_sku,
        user_id=user_id,
        guest_email=None,
        timezone="Europe/Kiev",
    )

    assert await review_reason(db_session, order) is None


# ---------- target-only linking (rules 2-4's delivery-target key) ----------


async def _paid_order_with_target(
    db: AsyncSession,
    *,
    sku_id: str,
    guest_email: str,
    total_usd: str,
    paid_at_minutes_ago: int,
    ip: str,
    target: str,
) -> Order:
    """A paid catalog order for one SKU whose ``fulfillment_data`` carries a
    delivery target, with its own guest email and IP — both deliberately
    unique per order, so any link `_gather` finds has to come through the
    target, not through buyer or IP.
    """
    moment = now()
    order = Order(
        id=new_id(),
        guest_email=guest_email,
        status="paid",
        currency="USD",
        total_usd=Decimal(total_usd),
        total_charged=Decimal(total_usd),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment - timedelta(minutes=paid_at_minutes_ago),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderItem(
            id=new_id(),
            order_id=order.id,
            sku_id=sku_id,
            qty=1,
            unit_price_usd=Decimal(total_usd),
            fulfillment_data={"username": target},
        )
    )
    db.add(
        OrderEvidence(
            order_id=order.id,
            ip=ip,
            purge_after=moment + timedelta(days=180),
        )
    )
    await db.flush()
    return order


async def test_two_orders_linked_only_by_target_cross_the_rolling_sum_cap(
    db_session: AsyncSession, _liquid_sku: str
) -> None:
    """Different buyers, different IPs — only the delivery target
    (`order_items.fulfillment_data`) links these three orders, in different
    cases/whitespace/`@`-forms to also exercise the SQL normalisation
    (`lower(ltrim(btrim(...), '@'))`) against the Python one (`_targets_from`).

    This is the SQL target path (`jsonb_each_text`) end to end — the final
    reviewer flagged it as never integration-exercised: the pure comparison
    in `_window_reason` is covered by
    `test_target_account_links_orders_with_nothing_else_shared` in
    `tests/unit/test_order_risk.py`, but nothing previously proved `_gather`'s
    own SQL actually finds these rows in Postgres.
    """
    await _paid_order_with_target(
        db_session,
        sku_id=_liquid_sku,
        guest_email="target-a@example.test",
        total_usd="11",
        paid_at_minutes_ago=60,
        ip="203.0.113.60",
        target="Durov",
    )
    await _paid_order_with_target(
        db_session,
        sku_id=_liquid_sku,
        guest_email="target-b@example.test",
        total_usd="11",
        paid_at_minutes_ago=120,
        ip="203.0.113.61",
        target="@durov",
    )
    current = await _paid_order_with_target(
        db_session,
        sku_id=_liquid_sku,
        guest_email="target-c@example.test",
        total_usd="11",
        paid_at_minutes_ago=0,
        ip="203.0.113.62",
        target=" Durov ",
    )
    await db_session.commit()

    assert await review_reason(db_session, current) == REASON_ROLLING_SUM


async def test_a_control_order_with_a_different_target_is_untouched(
    db_session: AsyncSession, _liquid_sku: str
) -> None:
    """Same shared target exists elsewhere, but this order's own target
    doesn't match it — nothing to link, in Postgres or in Python."""
    await _paid_order_with_target(
        db_session,
        sku_id=_liquid_sku,
        guest_email="target-d@example.test",
        total_usd="11",
        paid_at_minutes_ago=60,
        ip="203.0.113.63",
        target="durov",
    )
    await _paid_order_with_target(
        db_session,
        sku_id=_liquid_sku,
        guest_email="target-e@example.test",
        total_usd="11",
        paid_at_minutes_ago=120,
        ip="203.0.113.64",
        target="durov",
    )
    control = await _paid_order_with_target(
        db_session,
        sku_id=_liquid_sku,
        guest_email="target-f@example.test",
        total_usd="11",
        paid_at_minutes_ago=0,
        ip="203.0.113.65",
        target="someone-else",
    )
    await db_session.commit()

    assert await review_reason(db_session, control) is None


# ---------- device identity toggle (finding 4 / RISK_DEVICE_IDENTITY) ----------


async def _paid_guest_order_with_device(
    db: AsyncSession,
    *,
    guest_email: str,
    total_usd: str,
    paid_at_minutes_ago: int,
    ip: str,
    device_hash: str,
) -> Order:
    """Like `_paid_guest_order`, but also stamps `device_hash` on the
    evidence row -- the `risk_device_identity` toggle tests need a device
    fingerprint present to link (or, when the toggle is off, to confirm it
    does NOT link) on.
    """
    moment = now()
    order = Order(
        id=new_id(),
        guest_email=guest_email,
        status="paid",
        currency="USD",
        total_usd=Decimal(total_usd),
        total_charged=Decimal(total_usd),
        purpose="catalog",
        expires_at=moment + timedelta(days=1),
        paid_at=moment - timedelta(minutes=paid_at_minutes_ago),
    )
    db.add(order)
    await db.flush()
    db.add(
        OrderEvidence(
            order_id=order.id,
            ip=ip,
            device_hash=device_hash,
            purge_after=moment + timedelta(days=180),
        )
    )
    await db.flush()
    return order


async def test_device_identity_links_when_enabled(db_session: AsyncSession) -> None:
    """Different buyers, different IPs — only the device fingerprint links
    these three, and only once `risk_device_identity` is explicitly turned
    on. Off by default in production (`core.config.Settings`, and the
    runbook's collision query) because this audience's device hash collides
    across unrelated buyers too easily; this test proves the mechanism works
    once an operator opts in on traffic where it doesn't.
    """
    shared_device = "device-hash-shared-1"
    await _paid_guest_order_with_device(
        db_session,
        guest_email="dev-a@example.test",
        total_usd="11",
        paid_at_minutes_ago=60,
        ip="203.0.113.80",
        device_hash=shared_device,
    )
    await _paid_guest_order_with_device(
        db_session,
        guest_email="dev-b@example.test",
        total_usd="11",
        paid_at_minutes_ago=120,
        ip="203.0.113.81",
        device_hash=shared_device,
    )
    current = await _paid_guest_order_with_device(
        db_session,
        guest_email="dev-c@example.test",
        total_usd="11",
        paid_at_minutes_ago=0,
        ip="203.0.113.82",
        device_hash=shared_device,
    )
    await db_session.commit()

    base = get_settings().model_dump()
    base["risk_device_identity"] = True
    enabled = Settings(**base)

    assert await review_reason(db_session, current, settings=enabled) == REASON_ROLLING_SUM


async def test_device_identity_does_not_link_when_disabled(db_session: AsyncSession) -> None:
    """Same shared device fingerprint, same amounts as the test above — but
    under the default settings (`risk_device_identity=False`) device links
    nothing, so this order is untouched even though it would hold if the
    toggle were on.
    """
    shared_device = "device-hash-shared-2"
    await _paid_guest_order_with_device(
        db_session,
        guest_email="dev-d@example.test",
        total_usd="11",
        paid_at_minutes_ago=60,
        ip="203.0.113.83",
        device_hash=shared_device,
    )
    await _paid_guest_order_with_device(
        db_session,
        guest_email="dev-e@example.test",
        total_usd="11",
        paid_at_minutes_ago=120,
        ip="203.0.113.84",
        device_hash=shared_device,
    )
    current = await _paid_guest_order_with_device(
        db_session,
        guest_email="dev-f@example.test",
        total_usd="11",
        paid_at_minutes_ago=0,
        ip="203.0.113.85",
        device_hash=shared_device,
    )
    await db_session.commit()

    assert await review_reason(db_session, current) is None
