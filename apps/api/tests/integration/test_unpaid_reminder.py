"""One Telegram nudge for an order that expired before it was paid.

Drives ``orders.unpaid_reminder.send_unpaid_reminders`` against real Postgres:
what is being proven is the selection — who is ripe, who came back on their
own, and the caps that stop a buyer who tried five times hearing from us five
times. The message itself is stubbed.
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
from yupay.modules.notifications.service import (
    miniapp_brand_url,
    unpaid_reminder_text,
)
from yupay.modules.orders import unpaid_reminder as rem
from yupay.modules.orders.models import Order, OrderEvent
from yupay.modules.users.models import User

pytestmark = pytest.mark.asyncio


def _cfg(minutes: int) -> Settings:
    base = get_settings().model_dump()
    base["unpaid_reminder_after_minutes"] = minutes
    return Settings(**base)


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Capture what would have been messaged, and report success."""
    calls: list[tuple[str, str]] = []

    async def _fake(_db: Any, *, order_id: str, user_id: str) -> bool:
        calls.append((order_id, user_id))
        return True

    monkeypatch.setattr(rem, "notify_unpaid_reminder", _fake)
    return calls


@pytest.fixture
def unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """No linked Telegram."""

    async def _fake(_db: Any, *, order_id: str, user_id: str) -> bool:
        return False

    monkeypatch.setattr(rem, "notify_unpaid_reminder", _fake)


async def _user(db: AsyncSession) -> User:
    user = User(id=new_id(), email=None, locale="ru", display_currency="USD", roles=[])
    db.add(user)
    await db.flush()
    return user


async def _order(
    db: AsyncSession,
    *,
    user_id: str,
    age: timedelta,
    status: str = "expired",
    paid: bool = False,
) -> Order:
    moment = now()
    created = moment - age
    order = Order(
        id=new_id(),
        user_id=user_id,
        status=status,
        currency="USD",
        total_usd=Decimal("1.00"),
        total_charged=Decimal("1.00"),
        created_at=created,
        expires_at=created + timedelta(minutes=10),
        paid_at=created + timedelta(minutes=1) if paid else None,
    )
    db.add(order)
    await db.flush()
    return order


async def _events(db: AsyncSession, order_id: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(OrderEvent)
            .where(OrderEvent.order_id == order_id, OrderEvent.kind == rem.REMINDER_EVENT)
        )
    ).scalar_one()


async def test_zero_turns_it_off(db_session: AsyncSession, sent: list[Any]) -> None:
    user = await _user(db_session)
    await _order(db_session, user_id=user.id, age=timedelta(minutes=30))
    await db_session.commit()

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(0)) == 0
    assert sent == []


async def test_a_ripe_expired_order_is_nudged_once(
    db_session: AsyncSession, sent: list[tuple[str, str]]
) -> None:
    user = await _user(db_session)
    order = await _order(db_session, user_id=user.id, age=timedelta(minutes=30))
    await db_session.commit()

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 1
    assert sent == [(order.id, user.id)]
    assert await _events(db_session, order.id) == 1

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 0
    assert len(sent) == 1


async def test_too_fresh_and_too_old_are_left_alone(
    db_session: AsyncSession, sent: list[Any]
) -> None:
    """Fresh: the buyer may still come back alone. Old: the moment has passed."""
    fresh, old = await _user(db_session), await _user(db_session)
    await _order(db_session, user_id=fresh.id, age=timedelta(minutes=12))
    await _order(db_session, user_id=old.id, age=rem.MAX_AGE + timedelta(minutes=5))
    await db_session.commit()

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 0
    assert sent == []


async def test_a_buyer_who_came_back_and_paid_is_not_chased(
    db_session: AsyncSession, sent: list[Any]
) -> None:
    user = await _user(db_session)
    await _order(db_session, user_id=user.id, age=timedelta(minutes=50))
    await _order(
        db_session, user_id=user.id, age=timedelta(minutes=40), status="delivered", paid=True
    )
    await db_session.commit()

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 0
    assert sent == []


async def test_a_buyer_paying_a_newer_order_right_now_is_not_chased(
    db_session: AsyncSession, sent: list[Any]
) -> None:
    user = await _user(db_session)
    await _order(db_session, user_id=user.id, age=timedelta(minutes=50))
    await _order(db_session, user_id=user.id, age=timedelta(minutes=2), status="pending_payment")
    await db_session.commit()

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 0
    assert sent == []


async def test_several_tries_mean_one_message_about_the_newest(
    db_session: AsyncSession, sent: list[tuple[str, str]]
) -> None:
    """Somebody whose payment failed four times hears from us once."""
    user = await _user(db_session)
    for minutes in (90, 70, 50):
        await _order(db_session, user_id=user.id, age=timedelta(minutes=minutes))
    newest = await _order(db_session, user_id=user.id, age=timedelta(minutes=30))
    await db_session.commit()

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 1
    assert sent == [(newest.id, user.id)]

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 0
    assert len(sent) == 1


async def test_guest_and_paid_orders_are_never_selected(
    db_session: AsyncSession, sent: list[Any]
) -> None:
    moment = now()
    db_session.add(
        Order(
            id=new_id(),
            guest_email="guest@example.com",
            status="expired",
            currency="USD",
            total_usd=Decimal("1.00"),
            total_charged=Decimal("1.00"),
            created_at=moment - timedelta(minutes=30),
            expires_at=moment - timedelta(minutes=20),
        )
    )
    user = await _user(db_session)
    await _order(
        db_session, user_id=user.id, age=timedelta(minutes=30), status="delivered", paid=True
    )
    await db_session.commit()

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 0
    assert sent == []


async def test_a_buyer_with_no_telegram_is_recorded_and_not_retried(
    db_session: AsyncSession, unreachable: None
) -> None:
    user = await _user(db_session)
    order = await _order(db_session, user_id=user.id, age=timedelta(minutes=30))
    await db_session.commit()

    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 0
    assert await _events(db_session, order.id) == 1
    assert await rem.send_unpaid_reminders(db_session, settings=_cfg(20)) == 0
    assert await _events(db_session, order.id) == 1


async def test_the_button_opens_the_brand_page() -> None:
    base = "https://app.yupay.uz/"
    assert miniapp_brand_url(base, "free-fire") == "https://app.yupay.uz/topup/free-fire"
    assert miniapp_brand_url(base, "steam-gifts") == "https://app.yupay.uz/gifts"
    assert miniapp_brand_url(base, "cs2-skins") == "https://app.yupay.uz/cs2-market"
    assert miniapp_brand_url(base, None) == "https://app.yupay.uz/"


async def test_the_text_escapes_the_product_name() -> None:
    assert "&lt;b&gt;" in unpaid_reminder_text("<b>Roblox</b> · 100")
