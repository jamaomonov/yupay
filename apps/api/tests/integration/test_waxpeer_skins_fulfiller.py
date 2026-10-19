"""Buying a skin on Waxpeer and following the trade (plan 3a, Task 5).

A fake client stands in for Waxpeer; the database is real, so the ``skin_trades``
mirror is checked as it will be read by the order page and the sweeps.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.ids import new_id
from yupay.core.redis import get_redis
from yupay.modules.fulfillment.models import FulfillmentTask
from yupay.modules.fulfillment.suppliers.base import MoneyOutcome
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerError,
    WaxpeerUnavailableError,
)
from yupay.modules.fulfillment.suppliers.waxpeer_skins import fulfill_skin, skin_status
from yupay.modules.fulfillment.suppliers.waxpeer_trades import (
    WaxpeerBuy,
    WaxpeerBuyRefusedError,
    WaxpeerTrade,
)
from yupay.modules.orders.models import OrderItem
from yupay.modules.skins.listings import waxpeer_name_of
from yupay.modules.skins.models import SkinItem, SkinTrade

from tests.integration.test_fulfillment_async import _make_paid_order

pytestmark = pytest.mark.asyncio

LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s"
NAME = "AK-47 | Redline (Field-Tested)"
KEY = "task-key-1"
CHOSEN = 111
NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _trade(status: int, **over: Any) -> WaxpeerTrade:
    base = WaxpeerTrade(
        id=30717201,
        project_id=KEY,
        status=status,
        trade_id="9393511289" if status >= 2 else None,
        done=status in (5, 6),
        reason=None,
        release_date=None,
        is_released=False,
        send_until=NOW + timedelta(minutes=30),
        price_units=27867,
        penalties=None,
        seller={"name": "darpan6awx", "avatar_url": None, "level": 12, "joined_at": None},
    )
    return replace(base, **over)


class _Client:
    """Scripted Waxpeer: ``refuse`` item ids, ``live`` listings, ``trades`` lookups."""

    def __init__(
        self,
        *,
        trades: list[WaxpeerTrade] | None = None,
        refuse: set[int] | None = None,
        live: list[dict[str, Any]] | None = None,
        buy_error: Exception | None = None,
        lookup_error: Exception | None = None,
    ) -> None:
        self.trades = trades or []
        self.refuse = refuse or set()
        self.live = live or []
        self.buy_error = buy_error
        self.lookup_error = lookup_error
        self.bought: list[tuple[int, int]] = []
        self.searched: list[str] = []

    async def check_project_ids(self, ids: Sequence[str]) -> list[WaxpeerTrade]:
        if self.lookup_error:
            raise self.lookup_error
        return [t for t in self.trades if t.project_id in ids]

    async def buy_one_p2p(
        self, *, item_id: int, price_units: int, partner: int, token: str, project_id: str
    ) -> WaxpeerBuy:
        if self.buy_error:
            raise self.buy_error
        if item_id in self.refuse:
            raise WaxpeerBuyRefusedError("Item not found", new_price=None)
        self.bought.append((item_id, price_units))
        return WaxpeerBuy(id=30717201, price_units=price_units)

    async def search_listings(self, names: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        self.searched.extend(names)
        return {names[0]: self.live}


async def _item(
    db: AsyncSession,
    tag: str,
    *,
    expected_units: int = 27867,
    name: str = NAME,
    phase: str = "",
    tradelink: str = LINK,
) -> OrderItem:
    order = await _make_paid_order(db, tag=tag)
    item = (await db.execute(select(OrderItem).where(OrderItem.order_id == order.id))).scalar_one()
    slug = f"skin-{tag}-{new_id()[-6:]}"
    skin = SkinItem(
        id=new_id(),
        market_hash_name=name,
        phase=phase,
        slug=slug,
        category="knives" if phase else "rifles",
        search_text=name.lower(),
        active=True,
    )
    db.add(skin)
    item.fulfillment_data = {
        "slug": slug,
        "listing_id": CHOSEN,
        "tradelink": tradelink,
        "market_hash_name": name,
        "phase": phase,
        "name": f"{name} {phase}".strip(),
        "waxpeer_name": waxpeer_name_of(skin),
        "expected_units": expected_units,
    }
    await db.commit()
    await get_redis().delete("skins:wax:breaker")
    return item


async def _task(db: AsyncSession, item: OrderItem, **meta: Any) -> FulfillmentTask:
    task = FulfillmentTask(
        id=new_id(),
        order_id=item.order_id,
        order_item_id=item.id,
        supplier="waxpeer",
        status="in_progress",
        external_order_id=KEY,
        extra_metadata={"waxpeer_kind": "skin", **meta},
    )
    db.add(task)
    await db.commit()
    return task


async def _row(db: AsyncSession) -> SkinTrade:
    return (await db.execute(select(SkinTrade))).scalar_one()


async def test_buys_the_chosen_listing_at_the_paid_units(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-buy")
    client = _Client()
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert result.external_order_id == KEY
    assert result.extra_metadata["waxpeer_kind"] == "skin"
    assert client.bought == [(CHOSEN, 27867)]
    row = await _row(db_session)
    assert (row.project_id, row.waxpeer_id, row.bought_units) == (KEY, 30717201, 27867)


async def test_a_sold_listing_is_replaced_by_a_same_name_one_not_dearer(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "sk-sub")
    client = _Client(
        refuse={CHOSEN},
        live=[
            {"item_id": 222, "price": 28000, "auto": True},  # dearer than paid: skipped
            {"item_id": 333, "price": 27500, "auto": True},
            {"item_id": 444, "price": 27000, "auto": False},  # manual seller: never
        ],
    )
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert client.bought == [(333, 27500)]
    assert (await _row(db_session)).listing_id == 333


async def test_no_replacement_fails_with_the_money_back(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-none")
    client = _Client(refuse={CHOSEN}, live=[{"item_id": 222, "price": 99999, "auto": True}])
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert (result.outcome, result.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    assert result.error == "sold_out"


async def test_a_hidden_inventory_returns_the_money_without_substitutes(
    db_session: AsyncSession,
) -> None:
    """2026-10-20 on csmarket: four paid attempts, four refunds read as «sold out»."""
    item = await _item(db_session, "sk-hidden")
    client = _Client(
        buy_error=WaxpeerBuyRefusedError("Please set your steam inventory public", new_price=None),
        live=[{"item_id": 333, "price": 27000, "auto": True}],
    )
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert (result.outcome, result.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    assert result.error == "invalid_tradelink"
    assert client.searched == []  # no substitute: every lot would be refused the same way
    assert (await _row(db_session)).reason == "invalid_tradelink"


async def test_a_replayed_task_adopts_the_earlier_purchase(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-replay")
    client = _Client(trades=[_trade(2)])
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert client.bought == []
    assert (await _row(db_session)).status == 2


async def test_a_lost_buy_response_is_parked_not_retried(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-lost")
    client = _Client(buy_error=WaxpeerUnavailableError("timeout"))
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert "buy_unconfirmed_at" in result.extra_metadata


async def test_low_balance_fails_with_the_money_back(db_session: AsyncSession) -> None:
    # Owner's call 2026-09-29: a skin buyer is not kept waiting on our top-up —
    # nothing was bought, so the money goes back to their balance at once.
    item = await _item(db_session, "sk-low")
    client = _Client(buy_error=WaxpeerError("Not enough balance", status=200))
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert (result.outcome, result.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    assert result.error == "supplier_low_balance"
    assert result.extra_metadata["required_units"] == 27867
    assert (await _row(db_session)).reason == "supplier_low_balance"


async def test_status_follows_the_offer_to_acceptance(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-status")
    await fulfill_skin(_Client(), db=db_session, item=item, idempotency_key=KEY)
    task = await _task(db_session, item)

    sent = await skin_status(_Client(trades=[_trade(4)]), db=db_session, task=task)
    assert sent.outcome == "in_progress"
    row = await _row(db_session)
    assert (row.status, row.trade_id, row.accepted_at) == (4, "9393511289", None)
    assert row.seller["name"] == "darpan6awx"

    release = NOW + timedelta(days=7)
    accepted = await skin_status(
        _Client(trades=[_trade(4, release_date=release)]), db=db_session, task=task
    )
    assert accepted.outcome == "succeeded"
    assert accepted.artifact_kind == "topup_receipt"
    assert accepted.artifact is not None
    assert accepted.artifact["kind"] == "skin"
    assert accepted.artifact["trade_id"] == "9393511289"
    row = await _row(db_session)
    assert row.release_date == release
    assert row.accepted_at is not None


async def test_an_offer_not_accepted_fails_with_the_money_back(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-declined")
    await fulfill_skin(_Client(), db=db_session, item=item, idempotency_key=KEY)
    task = await _task(db_session, item)
    failed = await skin_status(
        _Client(trades=[_trade(6, reason="Buyer failed to accept")]), db=db_session, task=task
    )
    assert (failed.outcome, failed.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    assert failed.error == "not_accepted"
    assert (await _row(db_session)).reason == "Buyer failed to accept"


async def test_an_unconfirmed_buy_that_never_shows_up_is_unknown_after_10_minutes(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "sk-ghost")
    old = (datetime.now(UTC) - timedelta(minutes=11)).isoformat()
    task = await _task(db_session, item, buy_unconfirmed_at=old)
    status = await skin_status(_Client(trades=[]), db=db_session, task=task)
    assert (status.outcome, status.money_outcome) == ("failed", MoneyOutcome.UNKNOWN)


async def test_the_waxpeer_fulfiller_routes_skin_lines_and_tasks(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yupay.modules.fulfillment.suppliers import waxpeer as wx
    from yupay.modules.integrations.models import SkuSupplierMapping

    monkeypatch.setenv("WAXPEER_API_KEY", "k")
    from yupay.core import config as cfg

    cfg.get_settings.cache_clear()
    item = await _item(db_session, "sk-route")
    db_session.add(
        SkuSupplierMapping(
            sku_id=item.sku_id, supplier_slug="waxpeer", kind="skin", external_product_id="x"
        )
    )
    await db_session.commit()
    seen: list[str] = []

    async def fake_fulfill(client: object, **kw: Any) -> Any:
        seen.append("fulfill")
        return _failed_result()

    async def fake_status(client: object, **kw: Any) -> Any:
        seen.append("status")
        return _failed_status()

    monkeypatch.setattr(wx, "fulfill_skin", fake_fulfill)
    monkeypatch.setattr(wx, "skin_status", fake_status)
    ff = wx.WaxpeerFulfiller()
    order = item.order_id
    await ff.fulfill(db=db_session, order=order, item=item, idempotency_key=KEY)  # type: ignore[arg-type]
    task = await _task(db_session, item)
    await ff.check_status(db=db_session, task=task)
    assert seen == ["fulfill", "status"]
    cfg.get_settings.cache_clear()


def _failed_result() -> Any:
    from yupay.modules.fulfillment.suppliers.base import FulfillResult

    return FulfillResult(
        outcome="in_progress",
        external_order_id=KEY,
        artifact_kind=None,
        artifact=None,
        error=None,
        extra_metadata={},
        money_outcome=None,
    )


def _failed_status() -> Any:
    from yupay.modules.fulfillment.suppliers.base import FulfillStatus

    return FulfillStatus(
        outcome="in_progress", artifact_kind=None, artifact=None, error=None, money_outcome=None
    )


async def test_a_failed_first_lookup_defers_the_buy_to_the_sweep(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "sk-defer")
    down = _Client(lookup_error=WaxpeerUnavailableError("timeout"))
    result = await fulfill_skin(down, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert result.extra_metadata.get("buy_pending") is True
    assert "buy_unconfirmed_at" not in result.extra_metadata
    assert down.bought == []

    task = await _task(db_session, item, buy_pending=True)
    healthy = _Client()
    status = await skin_status(healthy, db=db_session, task=task)
    assert status.outcome == "in_progress"
    assert healthy.bought == [(CHOSEN, 27867)]
    assert status.extra_metadata["buy_pending"] is False


async def test_a_4xx_on_the_buy_means_nothing_was_bought(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-4xx")
    client = _Client(buy_error=WaxpeerError("bad request", status=400))
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert (result.outcome, result.money_outcome) == ("failed", MoneyOutcome.RETURNED)


async def test_the_trade_is_picked_by_waxpeers_id(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-pick")
    await fulfill_skin(_Client(), db=db_session, item=item, idempotency_key=KEY)
    task = await _task(db_session, item)
    release = NOW + timedelta(days=7)
    refused = _trade(6, id=11111, reason="Item not available")
    ours = _trade(4, release_date=release)  # id 30717201 = what we bought
    status = await skin_status(_Client(trades=[refused, ours]), db=db_session, task=task)
    assert status.outcome == "succeeded"


async def test_a_doppler_is_substituted_under_waxpeers_spelling(db_session: AsyncSession) -> None:
    item = await _item(
        db_session, "sk-doppler", name="★ Karambit | Doppler (Factory New)", phase="Phase 2"
    )
    client = _Client(refuse={CHOSEN}, live=[{"item_id": 555, "price": 27000, "auto": True}])
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert client.bought == [(555, 27000)]
    assert client.searched == ["★ Karambit | Doppler Phase 2 (Factory New)"]


async def test_a_rollback_after_acceptance_is_money_spent(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-rolled")
    await fulfill_skin(_Client(), db=db_session, item=item, idempotency_key=KEY)
    task = await _task(db_session, item)
    release = NOW + timedelta(days=7)
    await skin_status(_Client(trades=[_trade(4, release_date=release)]), db=db_session, task=task)
    penalties = {"total_penalty": 1500}
    failed = await skin_status(
        _Client(trades=[_trade(6, release_date=release, penalties=penalties)]),
        db=db_session,
        task=task,
    )
    assert (failed.outcome, failed.money_outcome) == ("failed", MoneyOutcome.SPENT)
    assert failed.error == "rolled_back"


async def test_a_bad_trade_link_fails_with_the_money_back_and_is_marked_skin(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "sk-badlink", tradelink="nope")
    result = await fulfill_skin(_Client(), db=db_session, item=item, idempotency_key=KEY)
    assert (result.outcome, result.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    assert result.extra_metadata["waxpeer_kind"] == "skin"


# ---------- edges the happy paths do not reach ----------


async def test_pick_trade_chooses_the_live_one_or_refuses_to_guess() -> None:
    from yupay.modules.fulfillment.suppliers.waxpeer_skins import AmbiguousTradeError, pick_trade

    failed, live, other = _trade(6), _trade(4, id=2), _trade(2, id=3)
    assert pick_trade([failed, live, other], 3) is other  # by Waxpeer's id
    assert pick_trade([failed, live], None) is live  # the one still alive
    latest = pick_trade([failed, _trade(6, id=9)], None)  # all failed: the latest
    assert latest is not None
    assert latest.id == 9
    with pytest.raises(AmbiguousTradeError):
        pick_trade([live, other], None)


async def test_an_unconfirmed_window_reads_bad_and_naive_timestamps() -> None:
    from yupay.modules.fulfillment.suppliers.waxpeer_skins import _unconfirmed_expired

    def task(raw: object) -> FulfillmentTask:
        return FulfillmentTask(extra_metadata={"buy_unconfirmed_at": raw})

    assert _unconfirmed_expired(task("not a date")) is True  # unreadable: stop waiting
    assert _unconfirmed_expired(task("2020-01-01T00:00:00")) is True  # naive, long ago
    assert _unconfirmed_expired(FulfillmentTask(extra_metadata={})) is False


async def test_a_5xx_on_the_buy_is_resolved_by_lookup_never_rebought(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "sk-5xx")
    client = _Client(buy_error=WaxpeerError("bad gateway", status=502))
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert "buy_unconfirmed_at" in result.extra_metadata


async def test_two_live_trades_on_the_first_lookup_buy_nothing(db_session: AsyncSession) -> None:
    item = await _item(db_session, "sk-amb1")
    client = _Client(trades=[_trade(2), _trade(4, id=2)])
    result = await fulfill_skin(client, db=db_session, item=item, idempotency_key=KEY)
    assert result.outcome == "in_progress"
    assert client.bought == []


async def test_two_live_trades_on_the_status_check_fail_it_unknown(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "sk-amb2")
    await fulfill_skin(_Client(), db=db_session, item=item, idempotency_key=KEY)
    row = await _row(db_session)
    row.waxpeer_id = None
    await db_session.commit()
    task = await _task(db_session, item)
    status = await skin_status(
        _Client(trades=[_trade(2), _trade(4, id=2)]), db=db_session, task=task
    )
    assert (status.outcome, status.money_outcome) == ("failed", MoneyOutcome.UNKNOWN)
    assert status.error == "ambiguous_trade"
    assert (await _row(db_session)).reason == "ambiguous_trade"


async def test_a_postponed_buy_with_a_broken_link_fails_with_the_money_back(
    db_session: AsyncSession,
) -> None:
    item = await _item(db_session, "sk-pend-bad")
    task = await _task(db_session, item, buy_pending=True)
    item.fulfillment_data = {**(item.fulfillment_data or {}), "tradelink": "nope"}
    await db_session.commit()
    status = await skin_status(_Client(), db=db_session, task=task)
    assert (status.outcome, status.money_outcome) == ("failed", MoneyOutcome.RETURNED)
    assert status.error == "invalid_tradelink"
