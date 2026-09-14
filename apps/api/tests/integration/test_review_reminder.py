"""The second ask: one Telegram reminder for a delivered order nobody rated.

Drives ``reviews.reminder.send_review_reminders`` against real Postgres,
because what is being proven is the selection query — who is ripe, who was
already asked, and the two caps that stop somebody with nine unreviewed
orders hearing from us nine times. The message itself is stubbed; whether
Telegram accepts it is ``notifications``' problem, not this one's.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.ids import new_id
from yupay.modules.catalog.models import Brand, Category, CategoryTranslation
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.reviews import reminder as rem
from yupay.modules.reviews.models import Review
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


def _cfg(hours: int) -> Settings:
    base = get_settings().model_dump()
    base["review_reminder_after_hours"] = hours
    return Settings(**base)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Capture what would have been messaged, and report success."""
    calls: list[tuple[str, str]] = []

    async def _fake(_db: Any, *, order_id: str, user_id: str) -> bool:
        calls.append((order_id, user_id))
        return True

    monkeypatch.setattr(rem, "notify_review_reminder", _fake)
    return calls


@pytest.fixture
def unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nobody on the other end — no linked Telegram, or no Mini App URL."""

    async def _fake(_db: Any, *, order_id: str, user_id: str) -> bool:
        return False

    monkeypatch.setattr(rem, "notify_review_reminder", _fake)


async def _user(db: AsyncSession) -> User:
    user = User(id=new_id(), email=None, locale="ru", display_currency="USD", roles=[])
    db.add(user)
    await db.flush()
    return user


async def _delivered(db: AsyncSession, *, user_id: str, age: timedelta) -> Order:
    moment = now()
    order = Order(
        id=new_id(),
        user_id=user_id,
        status="delivered",
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        created_at=moment - age,
        expires_at=moment,
        delivered_at=moment - age,
    )
    db.add(order)
    await db.flush()
    return order


async def _brand(db: AsyncSession, slug: str) -> Brand:
    cat = Category(id=new_id(), slug=f"cat-{slug}", sort_order=0, active=True)
    cat.translations = [CategoryTranslation(locale="ru", name="Cat")]
    db.add(cat)
    await db.flush()
    brand = Brand(id=new_id(), slug=slug, category_id=cat.id, sort_order=0, active=True)
    db.add(brand)
    await db.flush()
    return brand


async def _events(db: AsyncSession, order_id: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(OrderEvent)
            .where(OrderEvent.order_id == order_id, OrderEvent.kind == rem.REMINDER_EVENT)
        )
    ).scalar_one()


async def test_off_by_default_sends_nothing(db_session: AsyncSession, sent: list[Any]) -> None:
    """The setting is the only switch, and it starts at 0.

    This one messages real customers. A deploy must not be able to turn it on.
    """
    user = await _user(db_session)
    await _delivered(db_session, user_id=user.id, age=timedelta(days=2))
    await db_session.commit()

    assert await rem.send_review_reminders(db_session, settings=_cfg(0)) == 0
    assert sent == []


async def test_a_ripe_unreviewed_order_is_asked_about_once(
    db_session: AsyncSession, sent: list[tuple[str, str]]
) -> None:
    user = await _user(db_session)
    order = await _delivered(db_session, user_id=user.id, age=timedelta(days=2))
    await db_session.commit()

    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 1
    assert sent == [(order.id, user.id)]
    assert await _events(db_session, order.id) == 1

    # The event is what makes it once. Without it this order comes back every
    # hour for a fortnight.
    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 0
    assert len(sent) == 1


async def test_an_order_too_fresh_to_ask_about_is_left_alone(
    db_session: AsyncSession, sent: list[Any]
) -> None:
    """The delivery message already asked, minutes ago."""
    user = await _user(db_session)
    await _delivered(db_session, user_id=user.id, age=timedelta(hours=2))
    await db_session.commit()

    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 0
    assert sent == []


async def test_an_order_past_the_asking_window_is_left_alone(
    db_session: AsyncSession, sent: list[Any]
) -> None:
    """Same ceiling as the in-app prompt: a three-week-old top-up is history."""
    user = await _user(db_session)
    await _delivered(db_session, user_id=user.id, age=timedelta(days=20))
    await db_session.commit()

    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 0
    assert sent == []


async def test_an_order_that_was_reviewed_is_not_chased(
    db_session: AsyncSession, sent: list[Any]
) -> None:
    user = await _user(db_session)
    order = await _delivered(db_session, user_id=user.id, age=timedelta(days=2))
    brand = await _brand(db_session, "steam")
    db_session.add(
        Review(id=new_id(), brand_id=brand.id, user_id=user.id, order_id=order.id, rating=5)
    )
    await db_session.commit()

    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 0
    assert sent == []


async def test_one_person_hears_about_one_order_not_all_of_them(
    db_session: AsyncSession, sent: list[tuple[str, str]]
) -> None:
    """Both caps at once: newest order only, then silence for a week.

    Somebody who bought nine times and rated none of them is the exact person
    a naive query turns into nine notifications.
    """
    user = await _user(db_session)
    for days in (2, 3, 4):
        await _delivered(db_session, user_id=user.id, age=timedelta(days=days))
    newest = await _delivered(db_session, user_id=user.id, age=timedelta(days=1, hours=12))
    await db_session.commit()

    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 1
    assert sent == [(newest.id, user.id)]

    # The cooldown, not the per-order event, is what holds the other three.
    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 0
    assert len(sent) == 1


async def test_two_people_are_each_asked_in_the_same_run(
    db_session: AsyncSession, sent: list[tuple[str, str]]
) -> None:
    """One per *user*, not one per run — the cap must not serialise the batch."""
    first, second = await _user(db_session), await _user(db_session)
    a = await _delivered(db_session, user_id=first.id, age=timedelta(days=2))
    b = await _delivered(db_session, user_id=second.id, age=timedelta(days=2))
    await db_session.commit()

    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 2
    assert {order_id for order_id, _ in sent} == {a.id, b.id}


async def test_a_buyer_with_no_telegram_is_recorded_and_not_retried(
    db_session: AsyncSession, unreachable: None
) -> None:
    """Nothing was sent, but the order must still stop coming back.

    Without the event this order is re-selected every hour for a fortnight, and
    re-asking a channel that does not exist is not worth retrying.
    """
    user = await _user(db_session)
    order = await _delivered(db_session, user_id=user.id, age=timedelta(days=2))
    await db_session.commit()

    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 0
    assert await _events(db_session, order.id) == 1
    assert await rem.send_review_reminders(db_session, settings=_cfg(24)) == 0
    assert await _events(db_session, order.id) == 1
