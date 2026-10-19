"""@HUMOcardbot notification -> journal -> reservation -> deposit (spec §5.4)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.core.errors import AppError
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
OWNER_ID = 555000222


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
    s.owner_telegram_user_id = OWNER_ID
    s.business_connection_id = "bc1"
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
    assert r.holds_amount is True
    assert r.quarantine_until == r.created_at + timedelta(minutes=11)
    assert r.closed_at is not None
    assert r.incoming_id is not None
    assert await deposit_balance(db_session, merchant_id=m) == before + r.amount_usd


async def test_a_paid_amount_stays_quarantined_so_a_repeat_transfer_credits_nobody(
    db_session: AsyncSession,
) -> None:
    """Final review #1: a payer's accidental second transfer must not pay reseller B."""
    m, r1 = await _setup(db_session)
    paid_at = r1.created_at + timedelta(minutes=1)
    first = await intake.ingest_update(
        db_session,
        _update(30, _credit("50.000,00", _bank(r1.created_at), "1.100.000,00")),
        received_at=paid_at,
    )
    assert first.status == "matched"

    b = await _merchant(db_session)
    await _open(db_session, [m, b])
    r2 = await reservations.reserve(
        db_session, merchant_id=b, amount_uzs=50_000, idempotency_key=None
    )
    assert r2.amount_uzs == 50_001
    b_before = await deposit_balance(db_session, merchant_id=b)

    again = await intake.ingest_update(
        db_session,
        _update(31, _credit("50.000,00", _bank(r2.created_at), "1.150.000,00")),
        received_at=r2.created_at,
    )
    assert again.status == "unmatched"
    assert await deposit_balance(db_session, merchant_id=b) == b_before

    swept = await reservations.sweep(db_session, now_=paid_at + timedelta(minutes=10))
    assert swept.released >= 1
    await db_session.refresh(r1)
    assert r1.holds_amount is False
    c = await _merchant(db_session)
    await _open(db_session, [m, b, c])
    r3 = await reservations.reserve(
        db_session, merchant_id=c, amount_uzs=50_000, idempotency_key=None
    )
    assert r3.amount_uzs == 50_000


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
    [("50.000,50", "3311"), ("50.001,00", "3311")],
)
async def test_tiyin_or_other_amount_never_match(
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


async def test_a_card_that_is_not_ours_is_ignored_and_never_pays(
    db_session: AsyncSession,
) -> None:
    """csmarket's card reaches us through the shared bot: not money to resolve."""
    _, r = await _setup(db_session)
    t = _bank(r.created_at)
    await intake.ingest_update(
        db_session,
        _update(5, _credit("1.000,00", t, "101.000,00", "9999")),
        received_at=r.created_at,
    )
    res = await intake.ingest_update(
        db_session,
        _update(6, _credit("50.000,00", t, "999.000,00", "9999")),
        received_at=r.created_at,
    )
    assert res.status == "ignored"
    assert res.alerts == []  # no chain-break alert for someone else's balance
    row = await db_session.scalar(select(P2PIncoming).where(P2PIncoming.telegram_message_id == 6))
    assert row is not None
    assert row.result == "ignored"
    await db_session.refresh(r)
    assert r.status == "pending"


async def test_a_transfer_to_our_inactive_card_stays_unmatched(db_session: AsyncSession) -> None:
    await _card(db_session, active=False, pan_last4="4242")
    _, r = await _setup(db_session)
    res = await intake.ingest_update(
        db_session,
        _update(7, _credit("50.000,00", _bank(r.created_at), "1.100.000,00", "4242")),
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


@pytest.mark.parametrize(
    ("sweep_after", "status"),
    [(timedelta(minutes=2), "matched"), (timedelta(minutes=11), "unmatched")],
    ids=["inside-quarantine", "after-quarantine"],
)
async def test_late_delivery_of_an_on_time_transfer_matches_only_inside_quarantine(
    db_session: AsyncSession, sweep_after: timedelta, status: str
) -> None:
    """Final review #3: a redelivery matches while the amount is still held.

    The sweep expired the reservation and the bank time says the transfer was
    on time. Delivered while quarantined (``expires_at + 10 min``) it matches;
    once the sweep has released the amount it lands ``unmatched`` and support
    resolves it.
    """
    _, r = await _setup(db_session)
    await reservations.sweep(db_session, now_=r.expires_at + sweep_after)
    res = await intake.ingest_update(
        db_session,
        _update(7, _credit("50.000,00", _bank(r.created_at), "1.100.000,00")),
        received_at=r.expires_at + max(sweep_after, timedelta(minutes=5)),
    )
    assert res.status == status


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


async def test_inactive_twin_with_the_same_last4_does_not_block_a_match(
    db_session: AsyncSession,
) -> None:
    await _card(db_session, active=False)
    _, r = await _setup(db_session)
    res = await intake.ingest_update(
        db_session,
        _update(20, _credit("50.000,00", _bank(r.created_at), "1.100.000,00")),
        received_at=r.created_at,
    )
    assert res.status == "matched"


async def test_two_active_cards_with_one_last4_are_never_auto_matched(
    db_session: AsyncSession,
) -> None:
    _, r = await _setup(db_session)
    await _card(db_session)
    res = await intake.ingest_update(
        db_session,
        _update(21, _credit("50.000,00", _bank(r.created_at), "1.100.000,00")),
        received_at=r.created_at,
    )
    assert res.status == "unmatched"
    assert any(kind == "p2p_ambiguous_card" for kind, _ in res.alerts)
    await db_session.refresh(r)
    assert r.status == "pending"


async def test_a_transfer_older_than_the_reservation_cannot_pay_it(
    db_session: AsyncSession,
) -> None:
    _, r = await _setup(db_session)
    before = _bank(r.created_at - timedelta(minutes=3))
    res = await intake.ingest_update(
        db_session,
        _update(22, _credit("50.000,00", before, "1.100.000,00")),
        received_at=r.created_at,
    )
    assert res.status == "unmatched"


def _connection(conn_id: str, user_id: int, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "update_id": 23,
        "business_connection": {
            "id": conn_id,
            "user": {"id": user_id, "is_bot": False, "first_name": "x"},
            "user_chat_id": user_id,
            "date": 0,
            "is_enabled": enabled,
            "rights": {"can_reply": True},
        },
    }


async def test_a_business_connection_update_is_dropped(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    res = await intake.ingest_update(
        db_session, _connection("bc1", OWNER_ID), received_at=r.created_at
    )
    assert res.status == "dropped"


async def test_a_connection_from_a_non_owner_is_not_stored(db_session: AsyncSession) -> None:
    """Final review #2: anyone with Premium can connect the bot to their own account."""
    _, r = await _setup(db_session)
    await intake.ingest_update(db_session, _connection("evil", 1234), received_at=r.created_at)
    assert (await load_settings(db_session)).business_connection_id == "bc1"


async def test_the_owners_connection_is_stored(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    await intake.ingest_update(db_session, _connection("bc2", OWNER_ID), received_at=r.created_at)
    assert (await load_settings(db_session)).business_connection_id == "bc2"


async def test_a_disable_update_clears_the_stored_connection(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    await intake.ingest_update(
        db_session, _connection("bc1", OWNER_ID, enabled=False), received_at=r.created_at
    )
    assert (await load_settings(db_session)).business_connection_id is None


async def test_a_message_from_a_foreign_connection_is_dropped(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    u = _update(24, _credit("50.000,00", _bank(r.created_at), "1.100.000,00"))
    u["business_message"]["business_connection_id"] = "evil"
    res = await intake.ingest_update(db_session, u, received_at=r.created_at)
    assert res.status == "dropped"
    assert await db_session.scalar(select(func.count()).select_from(P2PIncoming)) == 0


async def test_with_no_connection_stored_everything_is_dropped(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    (await load_settings(db_session)).business_connection_id = None
    res = await intake.ingest_update(
        db_session,
        _update(25, _credit("50.000,00", _bank(r.created_at), "1.100.000,00")),
        received_at=r.created_at,
    )
    assert res.status == "dropped"
    await db_session.refresh(r)
    assert r.status == "pending"


async def test_the_connection_log_line_never_carries_the_user_id(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, r = await _setup(db_session)
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Log:
        def info(self, event: str, **fields: Any) -> None:
            calls.append((event, fields))

    monkeypatch.setattr(intake, "log", _Log())
    await intake.ingest_update(db_session, _connection("bc2", OWNER_ID), received_at=r.created_at)
    assert calls == [
        ("p2p.business_connection", {"is_enabled": True, "rights": ["can_reply"], "owner": True})
    ]


def _rendezvous(monkeypatch: pytest.MonkeyPatch, *targets: tuple[object, str]) -> None:
    """Hold each patched coroutine until both racers reach it, so they truly overlap.

    Without this, one racer can finish before the other starts and the test would
    pass even with the row lock removed.
    """
    arrived = 0
    both = asyncio.Event()

    def wrap(fn: Any) -> Any:  # Any: wraps differently-typed coroutines alike
        async def waiting(*args: Any, **kwargs: Any) -> Any:
            nonlocal arrived
            arrived += 1
            if arrived >= 2:
                both.set()
            await asyncio.wait_for(both.wait(), timeout=5)
            return await fn(*args, **kwargs)

        return waiting

    for owner, name in targets:
        monkeypatch.setattr(owner, name, wrap(getattr(owner, name)))


async def test_two_concurrent_transfers_for_one_reservation_credit_it_once(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review #4: the row lock, not a read, decides which transfer pays."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        m, r = await _setup(setup)
        await setup.commit()
        before = await deposit_balance(setup, merchant_id=m)
    t = _bank(r.created_at)
    _rendezvous(monkeypatch, (intake, "_payable"))

    async def one(msg_id: int, balance: str) -> str:
        async with factory() as db:
            res = await intake.ingest_update(
                db,
                _update(msg_id, _credit("50.000,00", t, balance)),
                received_at=r.created_at + timedelta(minutes=1),
            )
            await db.commit()
            return res.status

    got = await asyncio.gather(one(40, "1.100.000,00"), one(41, "1.150.000,00"))
    assert sorted(got) == ["matched", "unmatched"]
    async with factory() as check:
        results = (await check.execute(select(P2PIncoming.result))).scalars().all()
        assert sorted(results) == ["matched", "unmatched"]
        row = await check.get(P2PReservation, r.id)
        assert row is not None
        assert row.status == "paid"
        assert await deposit_balance(check, merchant_id=m) == before + r.amount_usd


async def test_cancel_racing_a_credit_has_exactly_one_winner(
    db_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Final review #4: cancel and credit both lock the row; money follows the final state."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        m, r = await _setup(setup)
        await setup.commit()
        before = await deposit_balance(setup, merchant_id=m)
    _rendezvous(monkeypatch, (intake, "_payable"), (reservations, "_own"))

    async def credit() -> str:
        async with factory() as db:
            res = await intake.ingest_update(
                db,
                _update(50, _credit("50.000,00", _bank(r.created_at), "1.100.000,00")),
                received_at=r.created_at + timedelta(minutes=1),
            )
            await db.commit()
            return res.status

    async def cancel() -> str:
        async with factory() as db:
            try:
                await reservations.cancel(db, merchant_id=m, number=r.number)
            except AppError:
                await db.rollback()
                return "refused"
            await db.commit()
            return "cancelled"

    credited, cancelled = await asyncio.gather(credit(), cancel())
    assert (credited, cancelled) in {("matched", "refused"), ("unmatched", "cancelled")}
    async with factory() as check:
        row = await check.get(P2PReservation, r.id)
        assert row is not None
        balance = await deposit_balance(check, merchant_id=m)
    if credited == "matched":
        assert row.status == "paid"
        assert balance == before + r.amount_usd
    else:
        assert row.status == "cancelled"
        assert balance == before
