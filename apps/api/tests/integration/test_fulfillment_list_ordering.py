"""Integration tests for ``list_tasks_admin`` ordering.

The admin work queues (stuck / failed / manual retry) fetch a capped window
and sort client-side, so under a backlog larger than the cap the *server*
order decides which tasks survive. ``order="oldest"`` must keep the
longest-waiting — most overdue — tasks; the default ``"newest"`` keeps recent
activity on page one for the browse view. ``id`` is the deterministic tiebreak
when several tasks share a ``created_at`` (bulk creation).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fulfillment import service as ff_svc
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.orders.models import Order, OrderItem
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _seed_chain(db: AsyncSession) -> tuple[str, str]:
    """One User → Category → Brand → Product → Sku → Order, returning
    ``(order_id, sku_id)``.

    Each task in a test gets its own OrderItem (``order_item_id`` is unique per
    task), all hanging off this single order.
    """
    slug = uuid.uuid4().hex[:8]
    user_id = str(uuid.uuid4())
    cat_id = str(uuid.uuid4())
    brand_id = str(uuid.uuid4())
    product_id = str(uuid.uuid4())
    sku_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    db.add(
        User(
            id=user_id, email=f"u-{slug}@example.com", locale="ru", display_currency="USD", roles=[]
        )
    )
    await db.flush()
    db.add(Category(id=cat_id, slug=f"c-{slug}"))
    await db.flush()
    db.add(Brand(id=brand_id, slug=f"b-{slug}", category_id=cat_id))
    await db.flush()
    db.add(Product(id=product_id, slug=f"p-{slug}", brand_id=brand_id, kind="top_up"))
    await db.flush()
    db.add(Sku(id=sku_id, product_id=product_id, sku_code=f"sku-{slug}", price_usd=Decimal("1.00")))
    await db.flush()
    db.add(
        Order(
            id=order_id,
            user_id=user_id,
            guest_email=None,
            status="paid",
            currency="USD",
            total_usd=Decimal("1.00"),
            total_charged=Decimal("1.00"),
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    await db.flush()
    return order_id, sku_id


async def _add_task(
    db: AsyncSession,
    *,
    order_id: str,
    sku_id: str,
    created_at: datetime,
    task_id: str | None = None,
    status: str = "in_progress",
    supplier: str = "manual",
) -> str:
    item_id = str(uuid.uuid4())
    tid = task_id or str(uuid.uuid4())
    db.add(
        OrderItem(
            id=item_id, order_id=order_id, sku_id=sku_id, qty=1, unit_price_usd=Decimal("1.00")
        )
    )
    await db.flush()
    db.add(
        FulfillmentTask(
            id=tid,
            order_id=order_id,
            order_item_id=item_id,
            supplier=supplier,
            status=status,
            created_at=created_at,
        )
    )
    await db.flush()
    return tid


async def test_oldest_first_keeps_the_longest_waiting_under_a_cap(
    db_session: AsyncSession,
) -> None:
    """With more tasks than ``limit``, ``order="oldest"`` returns the oldest
    window (the overdue work queue), while the default ``"newest"`` returns the
    most recent — the two windows are disjoint here, proving the direction."""
    order_id, sku_id = await _seed_chain(db_session)
    base = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
    ids = []
    for i in range(4):  # t0 oldest … t3 newest
        ids.append(
            await _add_task(
                db_session, order_id=order_id, sku_id=sku_id, created_at=base + timedelta(minutes=i)
            )
        )
    await db_session.commit()

    oldest, total = await ff_svc.list_tasks_admin(db_session, order="oldest", limit=2)
    assert total == 4
    assert [t.id for t in oldest] == [ids[0], ids[1]]

    newest, _ = await ff_svc.list_tasks_admin(db_session, order="newest", limit=2)
    assert [t.id for t in newest] == [ids[3], ids[2]]


async def test_default_order_is_newest_first(db_session: AsyncSession) -> None:
    """The unqualified call (browse view) puts recent activity first."""
    order_id, sku_id = await _seed_chain(db_session)
    base = datetime(2026, 7, 2, 9, 0, tzinfo=UTC)
    old = await _add_task(db_session, order_id=order_id, sku_id=sku_id, created_at=base)
    new = await _add_task(
        db_session, order_id=order_id, sku_id=sku_id, created_at=base + timedelta(hours=1)
    )
    await db_session.commit()

    rows, _ = await ff_svc.list_tasks_admin(db_session)
    assert [t.id for t in rows] == [new, old]


async def test_id_tiebreak_is_deterministic_across_pages(db_session: AsyncSession) -> None:
    """Tasks sharing a ``created_at`` (bulk creation) page deterministically:
    ``id`` breaks the tie so no row is seen twice or skipped between pages."""
    order_id, sku_id = await _seed_chain(db_session)
    same = datetime(2026, 7, 3, 8, 0, tzinfo=UTC)
    for tid in (
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
    ):
        await _add_task(db_session, order_id=order_id, sku_id=sku_id, created_at=same, task_id=tid)
    await db_session.commit()

    page1, _ = await ff_svc.list_tasks_admin(db_session, order="oldest", limit=2, offset=0)
    page2, _ = await ff_svc.list_tasks_admin(db_session, order="oldest", limit=2, offset=2)
    seen = [t.id for t in page1] + [t.id for t in page2]
    assert seen == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000003",
    ]
