"""@HUMOcardbot notification -> journal -> reservation -> deposit (spec §5.4)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.modules.merchants.deposit import deposit_balance
from yupay.modules.p2p import intake, reservations
from yupay.modules.p2p.models import P2PIncoming, P2PReservation
from yupay.modules.p2p.parsing import TASHKENT
from yupay.modules.p2p.settings import load_settings

from tests.integration.p2p_fixtures import (  # noqa: F401  (_fixed_rate is autouse)
    _card,
    _fixed_rate,
    _merchant,
    _open,
)

pytestmark = pytest.mark.asyncio
HUMO_ID = 777000111


def _update(msg_id: int, text: str, *, sender: int = HUMO_ID, **extra: Any) -> dict[str, Any]:
    return {
        "update_id": msg_id,
        "business_message": {
            "message_id": msg_id,
            "business_connection_id": "bc1",
            "from": {"id": sender, "is_bot": True},
            "chat": {"id": sender, "type": "private"},
            "date": 0,
            "text": text,
            **extra,
        },
    }


def _credit(amount: str, when: str, balance: str, last4: str = "3311") -> str:
    return (
        f"🎉 Пополнение\n➕ {amount} UZS\n📍 UB P2P Uzcard2Humo>T\n"
        f"💳 HUMOCARD *{last4}\n🕓 {when}\n💰 {balance} UZS"
    )


def _bank(moment: datetime) -> str:
    return moment.astimezone(TASHKENT).strftime("%H:%M %d.%m.%Y")


async def _setup(db: AsyncSession) -> tuple[str, P2PReservation]:
    await _card(db)
    m = await _merchant(db)
    await _open(db, [m])
    s = await load_settings(db)
    s.humo_bot_user_id = HUMO_ID
    r = await reservations.reserve(db, merchant_id=m, amount_uzs=50_000, idempotency_key=None)
    return m, r


async def test_exact_amount_credits_the_deposit(db_session: AsyncSession) -> None:
    m, r = await _setup(db_session)
    before = await deposit_balance(db_session, merchant_id=m)

    res = await intake.ingest_update(
        db_session,
        _update(1, _credit("50.000,00", _bank(r.created_at), "1.100.000,00")),
        received_at=r.created_at + timedelta(minutes=1),
    )

    assert res.status == "matched"
    assert res.reservation_number == r.number
    await db_session.refresh(r)
    assert r.status == "paid"
    assert r.holds_amount is False
    assert r.quarantine_until is None
    assert r.closed_at is not None
    assert r.incoming_id is not None
    assert await deposit_balance(db_session, merchant_id=m) == before + r.amount_usd


async def test_the_same_message_twice_credits_once(db_session: AsyncSession) -> None:
    m, r = await _setup(db_session)
    before = await deposit_balance(db_session, merchant_id=m)
    u = _update(2, _credit("50.000,00", _bank(r.created_at), "1.100.000,00"))
    first = await intake.ingest_update(db_session, u, received_at=r.created_at)
    second = await intake.ingest_update(db_session, u, received_at=r.created_at)
    assert (first.status, second.status) == ("matched", "duplicate")
    assert await db_session.scalar(select(func.count()).select_from(P2PIncoming)) == 1
    assert await deposit_balance(db_session, merchant_id=m) == before + r.amount_usd


async def test_second_same_amount_is_unmatched(db_session: AsyncSession) -> None:
    """Review Focus 1."""
    _, r = await _setup(db_session)
    t = _bank(r.created_at)
    a = await intake.ingest_update(
        db_session,
        _update(3, _credit("50.000,00", t, "1.100.000,00")),
        received_at=r.created_at,
    )
    b = await intake.ingest_update(
        db_session,
        _update(4, _credit("50.000,00", t, "1.150.000,00")),
        received_at=r.created_at,
    )
    assert (a.status, b.status) == ("matched", "unmatched")


@pytest.mark.parametrize(
    ("amount", "last4"),
    [("50.000,50", "3311"), ("50.000,00", "9999"), ("50.001,00", "3311")],
)
async def test_tiyin_other_card_or_other_amount_never_match(
    db_session: AsyncSession, amount: str, last4: str
) -> None:
    """Review Focus 4."""
    _, r = await _setup(db_session)
    res = await intake.ingest_update(
        db_session,
        _update(5, _credit(amount, _bank(r.created_at), "1.100.000,00", last4)),
        received_at=r.created_at,
    )
    assert res.status == "unmatched"


async def test_bank_time_after_expiry_is_not_credited(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    late = r.expires_at + timedelta(minutes=1)
    res = await intake.ingest_update(
        db_session,
        _update(6, _credit("50.000,00", _bank(late), "1,00")),
        received_at=late,
    )
    assert res.status == "unmatched"


async def test_late_delivery_of_an_on_time_transfer_still_matches(
    db_session: AsyncSession,
) -> None:
    """Review Focus 2: the sweep expired it, the bank time says it was on time."""
    _, r = await _setup(db_session)
    await reservations.sweep(db_session, now_=r.expires_at + timedelta(minutes=2))
    res = await intake.ingest_update(
        db_session,
        _update(7, _credit("50.000,00", _bank(r.created_at), "1.100.000,00")),
        received_at=r.expires_at + timedelta(hours=3),
    )
    assert res.status == "matched"


async def test_cancelled_is_never_credited(db_session: AsyncSession) -> None:
    """Review Focus 5 (the cancel-first half)."""
    m, r = await _setup(db_session)
    await reservations.cancel(db_session, merchant_id=m, number=r.number)
    res = await intake.ingest_update(
        db_session,
        _update(8, _credit("50.000,00", _bank(r.created_at), "1.100.000,00")),
        received_at=r.created_at,
    )
    assert res.status == "unmatched"


@pytest.mark.parametrize(
    ("extra", "sender"), [({}, 1234), ({"forward_origin": {"type": "user"}}, HUMO_ID)]
)
async def test_foreign_or_forwarded_is_dropped(
    db_session: AsyncSession, extra: dict[str, Any], sender: int
) -> None:
    _, r = await _setup(db_session)
    u = _update(9, _credit("50.000,00", _bank(r.created_at), "1,00"), sender=sender, **extra)
    res = await intake.ingest_update(db_session, u, received_at=r.created_at)
    assert res.status == "dropped"
    assert await db_session.scalar(select(func.count()).select_from(P2PIncoming)) == 0


async def test_edited_message_is_dropped(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    u = _update(10, _credit("50.000,00", _bank(r.created_at), "1,00"))
    u["edited_business_message"] = u.pop("business_message")
    res = await intake.ingest_update(db_session, u, received_at=r.created_at)
    assert res.status == "dropped"


async def test_a_broken_balance_chain_raises_an_alert(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    t = _bank(r.created_at)
    await intake.ingest_update(
        db_session,
        _update(11, _credit("1.000,00", t, "101.000,00")),
        received_at=r.created_at,
    )
    res = await intake.ingest_update(
        db_session,
        _update(12, _credit("2.000,00", t, "999.000,00")),
        received_at=r.created_at,
    )
    assert any(kind == "p2p_chain_break" for kind, _ in res.alerts)


async def test_unparsed_is_journaled_and_alerts(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    res = await intake.ingest_update(
        db_session, _update(13, "Новый формат!"), received_at=r.created_at
    )
    assert res.status == "ignored"
    assert any(kind == "p2p_unparsed" for kind, _ in res.alerts)
    assert await db_session.scalar(select(func.count()).select_from(P2PIncoming)) == 1


async def test_route_refuses_a_wrong_secret_without_reading(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "yupay.api.webhooks.telegram_p2p.get_settings",
        lambda: SimpleNamespace(p2p_webhook_secret="s3cret"),
    )
    bad = await integration_client.post(
        "/api/v1/webhooks/telegram/p2p",
        content=b"not json",
        headers={"X-Telegram-Bot-Api-Secret-Token": "nope"},
    )
    assert bad.status_code == 401
    ok = await integration_client.post(
        "/api/v1/webhooks/telegram/p2p",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert ok.status_code == 200


async def test_route_with_no_secret_configured_refuses_everything(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "yupay.api.webhooks.telegram_p2p.get_settings",
        lambda: SimpleNamespace(p2p_webhook_secret=""),
    )
    res = await integration_client.post("/api/v1/webhooks/telegram/p2p", json={"update_id": 1})
    assert res.status_code == 401
