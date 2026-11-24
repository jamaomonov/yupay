"""Contract tests for ``FoxreloadFulfiller`` (ADR-0107) against the real client.

HTTP is mocked with respx in the shapes of their OpenAPI document (2026-11-24).
What is pinned: whole dollars only and refused before any call otherwise; one
order per key even after a lost create; ``pay`` only on an unpaid order; a lost
``pay`` finished by the poll; their refund graded RETURNED; low balance as the
soft stall; and the router sending a line it cannot take to the overflow.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from yupay.core import config as cfg
from yupay.modules.fulfillment import service as fsvc
from yupay.modules.fulfillment.suppliers import foxreload as fox_mod
from yupay.modules.fulfillment.suppliers.base import FulfillerError, MoneyOutcome
from yupay.modules.fulfillment.suppliers.foxreload import (
    LOW_BALANCE_ERROR,
    FoxreloadFulfiller,
    takes_line,
)

BASE = "https://fox.test"
PRODUCT = "product_steam_usd"
ORDER_ID = "0190f0f0-0000-7000-8000-000000000001"


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("FOXRELOAD_API_KEY", "fox-key")
    monkeypatch.setenv("FOXRELOAD_BASE_URL", BASE)
    monkeypatch.setenv("FOXRELOAD_OVERFLOW_SUPPLIER", "waxpeer")
    cfg.get_settings.cache_clear()

    async def _product(_db: Any, *, sku_id: str) -> str:
        return PRODUCT

    monkeypatch.setattr(fox_mod, "_product_id", _product)
    yield
    cfg.get_settings.cache_clear()


def _item(usd: str = "10", *, login: str | None = "gaben", qty: int = 1) -> Any:
    return SimpleNamespace(
        id="item-1",
        sku_id="sku-steam",
        qty=qty,
        unit_price_usd=Decimal(usd),
        fulfillment_data={"steam_login": login} if login else {},
    )


def _order(status: str, *, refunded: str | None = None, error: str | None = None) -> dict[str, Any]:
    return {
        "id": ORDER_ID,
        "idempotencyKey": "k1",
        "price": "9.549",
        "currency": "usd",
        "refundedAmount": refunded,
        "status": status,
        "items": [
            {
                "id": "it-1",
                "index": 0,
                "quantity": 10,
                "fulfillmentStatus": "failed" if error else "processing",
                "externalData": [],
                "externalId": None,
                "error": error,
            }
        ],
    }


def _err(status: int, code: str) -> httpx.Response:
    return httpx.Response(status, json={"detail": "x", "code": code})


class _DB:
    def __init__(self, item: Any) -> None:
        self._item = item

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(scalar_one=lambda: self._item)


async def _fulfill(item: Any) -> Any:
    return await FoxreloadFulfiller().fulfill(
        db=_DB(item),  # type: ignore[arg-type]
        order=SimpleNamespace(),  # type: ignore[arg-type]
        item=item,
        idempotency_key="k1",
    )


async def test_creates_pays_and_waits_on_a_whole_dollar_line() -> None:
    with respx.mock(base_url=BASE) as mock:
        create = mock.post("/api/orders/").respond(200, json=_order("active"))
        pay = mock.post(f"/api/orders/{ORDER_ID}/pay").respond(200, json={"id": "p1"})
        mock.get(f"/api/orders/{ORDER_ID}").respond(200, json=_order("processing"))
        result = await _fulfill(_item("10"))

    assert result.outcome == "in_progress"
    assert result.external_order_id == ORDER_ID
    assert pay.called
    sent = create.calls.last.request
    assert json.loads(sent.content) == {
        "items": [{"itemId": PRODUCT, "quantity": 10, "note": {"login": "gaben"}}],
        "idempotencyKey": "k1",
    }
    assert sent.headers["X-API-Key"] == "fox-key"
    assert sent.headers["X-Currency"] == "usd"


async def test_a_completed_order_is_a_receipt() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/orders/").respond(200, json=_order("active"))
        mock.post(f"/api/orders/{ORDER_ID}/pay").respond(200, json={"id": "p1"})
        mock.get(f"/api/orders/{ORDER_ID}").respond(200, json=_order("completed"))
        result = await _fulfill(_item("25"))

    assert result.outcome == "succeeded"
    assert result.artifact_kind == "topup_receipt"
    assert result.artifact["amount_usd"] == 25
    assert result.artifact["source"] == "foxreload"


@pytest.mark.parametrize("usd", ["10.50", "0", "176"])
async def test_a_line_it_cannot_sell_is_refused_before_any_call(usd: str) -> None:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        route = mock.post("/api/orders/")
        with pytest.raises(FulfillerError) as caught:
            await _fulfill(_item(usd))
    assert not route.called
    assert caught.value.money_outcome is MoneyOutcome.RETURNED


async def test_a_repeated_key_finds_the_order_instead_of_buying_again() -> None:
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.post("/api/orders/").mock(return_value=_err(400, "ORDER_ALREADY_EXISTS"))
        listing = mock.get("/api/orders/").respond(200, json={"items": [{"id": ORDER_ID}]})
        mock.get(f"/api/orders/{ORDER_ID}").respond(200, json=_order("completed"))
        pay = mock.post(f"/api/orders/{ORDER_ID}/pay")
        result = await _fulfill(_item("10"))

    assert listing.calls.last.request.url.params["idempotencyKey"] == "k1"
    assert not pay.called  # already paid and delivered
    assert result.outcome == "succeeded"


async def test_a_create_that_never_answered_spent_nothing() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/orders/").respond(502)
        with pytest.raises(FulfillerError) as caught:
            await _fulfill(_item("10"))
    assert caught.value.money_outcome is MoneyOutcome.RETURNED


async def test_low_balance_is_the_soft_stall_with_the_balance() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/orders/").respond(200, json=_order("active"))
        mock.post(f"/api/orders/{ORDER_ID}/pay").mock(return_value=_err(400, "BALANCE_NOT_ENOUGH"))
        mock.get("/api/access/me/balances/").respond(
            200, json=[{"currency": "usd", "available": "3.2", "reserved": "0", "pending": "0"}]
        )
        result = await _fulfill(_item("10"))

    assert result.outcome == "failed"
    assert result.error == LOW_BALANCE_ERROR == fsvc._LOW_BALANCE_ERROR
    assert result.money_outcome is None
    assert result.extra_metadata["current_balance"] == "3.20"
    assert result.extra_metadata["required"] == "10.00"


async def test_a_lost_pay_answer_leaves_the_line_in_flight() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/orders/").respond(200, json=_order("active"))
        mock.post(f"/api/orders/{ORDER_ID}/pay").mock(side_effect=httpx.ReadTimeout("slow"))
        mock.get(f"/api/orders/{ORDER_ID}").respond(503)
        result = await _fulfill(_item("10"))

    assert result.outcome == "in_progress"
    assert result.money_outcome is None


async def test_the_poll_pays_an_order_still_unpaid() -> None:
    task = SimpleNamespace(external_order_id=ORDER_ID, order_item_id="item-1")
    item = _item("10")
    with respx.mock(base_url=BASE) as mock:
        mock.get(f"/api/orders/{ORDER_ID}").mock(
            side_effect=[
                httpx.Response(200, json=_order("active")),
                httpx.Response(200, json=_order("processing")),
            ]
        )
        pay = mock.post(f"/api/orders/{ORDER_ID}/pay").respond(200, json={"id": "p1"})
        status = await FoxreloadFulfiller().check_status(db=_DB(item), task=task)  # type: ignore[arg-type]

    assert pay.called
    assert status.outcome == "in_progress"


async def test_their_refund_returns_our_money_with_the_customer_reason() -> None:
    task = SimpleNamespace(external_order_id=ORDER_ID, order_item_id="item-1")
    item = _item("10")
    with respx.mock(base_url=BASE) as mock:
        mock.get(f"/api/orders/{ORDER_ID}").respond(
            200, json=_order("refunded", refunded="9.549", error="Аккаунт не найден")
        )
        status = await FoxreloadFulfiller().check_status(db=_DB(item), task=task)  # type: ignore[arg-type]

    assert status.outcome == "failed"
    assert status.money_outcome is MoneyOutcome.RETURNED
    assert "Аккаунт не найден" in (status.error or "")


async def test_failed_before_the_refund_lands_keeps_waiting() -> None:
    task = SimpleNamespace(external_order_id=ORDER_ID, order_item_id="item-1")
    item = _item("10")
    with respx.mock(base_url=BASE) as mock:
        mock.get(f"/api/orders/{ORDER_ID}").respond(200, json=_order("failed", error="x"))
        status = await FoxreloadFulfiller().check_status(db=_DB(item), task=task)  # type: ignore[arg-type]
    assert status.outcome == "in_progress"


def test_the_router_sends_what_foxreload_cannot_sell_to_the_overflow() -> None:
    assert takes_line(_item("10"))
    assert not takes_line(_item("10.50"))
    assert fsvc._overflow_route(_item("10"), "foxreload") == "foxreload"
    assert fsvc._overflow_route(_item("10.50"), "foxreload") == "waxpeer"
    assert fsvc._overflow_route(_item("400"), "foxreload") == "waxpeer"
    # Any other route is left alone, whatever the line.
    assert fsvc._overflow_route(_item("10.50"), "waxpeer") == "waxpeer"


def test_an_empty_overflow_keeps_the_line_on_foxreload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FOXRELOAD_OVERFLOW_SUPPLIER", "")
    cfg.get_settings.cache_clear()
    assert fsvc._overflow_route(_item("10.50"), "foxreload") == "foxreload"


async def test_the_charge_they_took_is_handed_to_the_margin() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/orders/").respond(200, json=_order("active"))
        mock.post(f"/api/orders/{ORDER_ID}/pay").respond(200, json={"id": "p1"})
        mock.get(f"/api/orders/{ORDER_ID}").respond(200, json=_order("completed"))
        result = await _fulfill(_item("10"))
    # $10 of wallet for $9.549: the margin sees the discount, not face value.
    assert result.extra_metadata["supplier_charged_usd"] == "9.549"


async def test_an_unpaid_order_states_no_charge() -> None:
    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/orders/").respond(200, json=_order("active"))
        mock.post(f"/api/orders/{ORDER_ID}/pay").mock(return_value=_err(400, "BALANCE_NOT_ENOUGH"))
        mock.get("/api/access/me/balances/").respond(200, json=[])
        result = await _fulfill(_item("10"))
    assert "supplier_charged_usd" not in result.extra_metadata
