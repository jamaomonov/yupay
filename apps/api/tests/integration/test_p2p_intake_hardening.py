"""Intake hardening: chain order, malformed updates, narrow duplicate catch, the route."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from yupay.modules.p2p import intake
from yupay.modules.p2p.models import P2PIncoming, P2PReservation
from yupay.modules.p2p.parsing import ParsedNotification

from tests.integration.p2p_fixtures import _fixed_rate  # noqa: F401  (autouse)
from tests.integration.test_p2p_intake import _bank, _credit, _setup, _update

pytestmark = pytest.mark.asyncio


class _Log:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def info(self, event: str, **fields: Any) -> None:
        self.calls.append((event, fields))

    warning = info


async def test_out_of_order_delivery_is_not_a_chain_break(db_session: AsyncSession) -> None:
    """Message 12 arrives before 11 in the same minute: neither is a false break."""
    _, r = await _setup(db_session)
    t = _bank(r.created_at)
    twelve = await intake.ingest_update(
        db_session, _update(12, _credit("2.000,00", t, "103.000,00")), received_at=r.created_at
    )
    eleven = await intake.ingest_update(
        db_session,
        _update(11, _credit("1.000,00", t, "101.000,00")),
        received_at=r.created_at + timedelta(seconds=1),
    )
    thirteen = await intake.ingest_update(
        db_session,
        _update(13, _credit("3.000,00", t, "106.000,00")),
        received_at=r.created_at + timedelta(seconds=2),
    )
    for res in (twelve, eleven, thirteen):
        assert not any(kind == "p2p_chain_break" for kind, _ in res.alerts)
    chain = dict(
        (await db_session.execute(select(P2PIncoming.telegram_message_id, P2PIncoming.chain_ok)))
        .tuples()
        .all()
    )
    assert chain == {11: None, 12: None, 13: True}


async def test_the_chain_only_follows_its_own_connection(db_session: AsyncSession) -> None:
    _, r = await _setup(db_session)
    t = _bank(r.created_at)
    db_session.add(
        P2PIncoming(
            id="00000000-0000-0000-0000-000000000001",
            business_connection_id="old",
            telegram_message_id=5,
            kind="credit",
            card_last4="3311",
            balance_after=1,
            raw_text="x",
            result="ignored",
            received_at=r.created_at,
        )
    )
    await db_session.flush()
    res = await intake.ingest_update(
        db_session, _update(6, _credit("1.000,00", t, "101.000,00")), received_at=r.created_at
    )
    assert not any(kind == "p2p_chain_break" for kind, _ in res.alerts)


@pytest.mark.parametrize(
    "message_id", [None, "12", 1.5, True], ids=["missing", "str", "float", "bool"]
)
async def test_a_malformed_message_id_is_dropped_not_a_500(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, message_id: object
) -> None:
    _, r = await _setup(db_session)
    rec = _Log()
    monkeypatch.setattr(intake, "log", rec)
    u = _update(1, _credit("50.000,00", _bank(r.created_at), "1.100.000,00"))
    if message_id is None:
        del u["business_message"]["message_id"]
    else:
        u["business_message"]["message_id"] = message_id
    res = await intake.ingest_update(db_session, u, received_at=r.created_at)
    assert res.status == "dropped"
    assert [event for event, _ in rec.calls] == ["p2p.malformed_update"]
    assert "50.000" not in repr(rec.calls)
    assert await db_session.scalar(select(func.count()).select_from(P2PIncoming)) == 0


async def test_only_the_message_key_counts_as_a_duplicate(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any other integrity failure must surface, not be filed as a Telegram retry."""
    _, r = await _setup(db_session)
    # model_construct skips validation: a kind the CHECK constraint refuses.
    bogus = ParsedNotification.model_construct(kind="bogus")  # type: ignore[arg-type]
    monkeypatch.setattr(intake, "parse_humo", lambda _text: bogus)
    with pytest.raises(IntegrityError):
        await intake.ingest_update(db_session, _update(1, "x"), received_at=r.created_at)


async def test_the_route_commits_before_it_alerts(
    integration_client: AsyncClient,
    db_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matched credit with a chain break: the alert sees the committed journal and payment."""
    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with factory() as setup:
        _, r = await _setup(setup)
        await intake.ingest_update(
            setup,
            _update(1, _credit("1.000,00", _bank(r.created_at), "500.000,00")),
            received_at=r.created_at,
        )
        await setup.commit()
    monkeypatch.setattr(
        "yupay.api.webhooks.telegram_p2p.get_settings",
        lambda: SimpleNamespace(p2p_webhook_secret="s3cret"),
    )
    seen: list[str] = []

    async def alert(text: str, *, kind: str, **_: object) -> bool:
        async with factory() as fresh:
            row = await fresh.scalar(
                select(P2PIncoming).where(P2PIncoming.telegram_message_id == 2)
            )
            assert row is not None
            assert row.result == "matched"
            paid = await fresh.get(P2PReservation, r.id)
            assert paid is not None
            assert paid.status == "paid"
        seen.append(kind)
        return True

    monkeypatch.setattr("yupay.api.webhooks.telegram_p2p.send_admin_alert", alert)
    res = await integration_client.post(
        "/api/v1/webhooks/telegram/p2p",
        json=_update(2, _credit("50.000,00", _bank(r.created_at), "999,00")),
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert res.status_code == 200, res.text
    assert seen == ["p2p_chain_break"]
