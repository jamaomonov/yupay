"""Contract tests for ``WaxpeerFulfiller``.

HTTP is mocked with respx against the real ``WaxpeerClient`` — nothing here
talks to the live Waxpeer API. The point of these tests is the status
mapping and reconciliation logic in the fulfiller, not the transport (that's
``test_waxpeer_client.py``'s job).
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
import respx
from yupay.core import config as cfg
from yupay.modules.fulfillment.suppliers.base import FulfillerError, FulfillerNotIntegratedError
from yupay.modules.fulfillment.suppliers.waxpeer import WaxpeerFulfiller
from yupay.modules.fulfillment.suppliers.waxpeer_client import WaxpeerClient

BASE = "https://api.waxpeer.test/v1"
API_KEY = "test-key"


@pytest.fixture(autouse=True)
def _waxpeer_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WAXPEER_API_KEY", API_KEY)
    monkeypatch.setenv("WAXPEER_BASE_URL", BASE)
    monkeypatch.setenv("WAXPEER_FEE_RATE", "0")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _item(
    *,
    unit_price_usd: Decimal = Decimal("10.00"),
    steam_login: str | None = "gaben",
    qty: int = 1,
) -> Any:
    return SimpleNamespace(
        id="item-0000000000ab",
        sku_id="sku-1",
        qty=qty,
        unit_price_usd=unit_price_usd,
        fulfillment_data={"steam_login": steam_login} if steam_login is not None else {},
    )


def _task(*, external_order_id: str | None, order_item_id: str = "item-0000000000ab") -> Any:
    return SimpleNamespace(external_order_id=external_order_id, order_item_id=order_item_id)


class _FakeDB:
    """Just enough AsyncSession for check_status's OrderItem lookup."""

    def __init__(self, item: Any) -> None:
        self._item = item

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(scalar_one=lambda: self._item)


def _topup_json(
    *,
    topup_id: int = 1,
    custom_id: str = "k1",
    status: str = "created",
    amount: int = 10000,
    give_amount: int | None = None,
    steam_login: str = "gaben",
) -> dict[str, Any]:
    return {
        "success": True,
        "topup": {
            "id": topup_id,
            "custom_id": custom_id,
            "status": status,
            "amount": amount,
            "give_amount": give_amount if give_amount is not None else amount,
            "steam_login": steam_login,
        },
    }


def _sent_body(route: respx.Route) -> dict[str, Any]:
    content = route.calls.last.request.content
    return cast(dict[str, Any], json.loads(content))


# ---------- fulfill: request shape ----------


@respx.mock
async def test_fulfill_sends_the_grossed_up_amount_and_the_order_key() -> None:
    """$10 with fee 0 posts amount=10000 and custom_id=<idempotency key>."""
    route = respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200, json=_topup_json(custom_id="ik-1", amount=10000, give_amount=10000)
        )
    )
    gw = WaxpeerFulfiller()
    await gw.fulfill(
        db=cast(Any, None),
        order=cast(Any, None),
        item=_item(unit_price_usd=Decimal("10.00")),
        idempotency_key="ik-1",
    )
    body = _sent_body(route)
    assert body["amount"] == 10000
    assert body["custom_id"] == "ik-1"
    assert body["steam_login"] == "gaben"


# ---------- fulfill: status mapping ----------


@respx.mock
async def test_fulfill_is_in_progress_until_steam_is_credited() -> None:
    """status=created ⇒ outcome "in_progress", external id recorded."""
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json=_topup_json(status="created"))
    )
    gw = WaxpeerFulfiller()
    result = await gw.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="ik-2"
    )
    assert result.outcome == "in_progress"
    assert result.external_order_id == "ik-2"
    assert result.artifact is None


@respx.mock
async def test_completed_maps_to_succeeded_with_a_receipt() -> None:
    """status=completed ⇒ "succeeded" and a topup_receipt artifact."""
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200, json=_topup_json(status="completed", amount=10000, give_amount=10000)
        )
    )
    gw = WaxpeerFulfiller()
    result = await gw.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="ik-3"
    )
    assert result.outcome == "succeeded"
    assert result.artifact_kind == "topup_receipt"
    assert result.artifact is not None
    assert result.artifact["source"] == "waxpeer"
    assert result.artifact["give_amount_units"] == 10000


@respx.mock
async def test_canceled_maps_to_failed_and_says_the_supplier_refunded() -> None:
    """status=canceled ⇒ "failed"; metadata marks the money as returned to us."""
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json=_topup_json(status="canceled"))
    )
    gw = WaxpeerFulfiller()
    result = await gw.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="ik-4"
    )
    assert result.outcome == "failed"
    assert result.extra_metadata["supplier_refunded"] is True
    assert result.error is not None
    assert "refund" in result.error.lower()


@respx.mock
async def test_error_maps_to_failed_and_flags_manual_reconciliation() -> None:
    """status=error ⇒ "failed" with needs_reconciliation, because Waxpeer does
    not refund this case automatically."""
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json=_topup_json(status="error"))
    )
    gw = WaxpeerFulfiller()
    result = await gw.fulfill(
        db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="ik-5"
    )
    assert result.outcome == "failed"
    assert result.extra_metadata["needs_reconciliation"] is True
    assert "supplier_refunded" not in result.extra_metadata
    assert result.error is not None
    assert "reconcil" in result.error.lower()


# ---------- fulfill: reconciliation ----------


@respx.mock
async def test_short_give_amount_is_flagged_not_swallowed() -> None:
    """give_amount below the promise records a discrepancy — this is how a
    newly-introduced supplier fee surfaces before customers complain."""
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200, json=_topup_json(status="completed", amount=10000, give_amount=9800)
        )
    )
    gw = WaxpeerFulfiller()
    result = await gw.fulfill(
        db=cast(Any, None),
        order=cast(Any, None),
        item=_item(unit_price_usd=Decimal("10.00")),
        idempotency_key="ik-6",
    )
    # Still delivered — the money already moved to the customer's wallet —
    # but the shortfall must be visible, not swallowed.
    assert result.outcome == "succeeded"
    assert result.extra_metadata["give_amount_shortfall_units"] == 200


@respx.mock
async def test_give_amount_meeting_the_promise_is_not_flagged() -> None:
    """No shortfall ⇒ no discrepancy key at all, so alerting can key on presence."""
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200, json=_topup_json(status="completed", amount=10000, give_amount=10000)
        )
    )
    gw = WaxpeerFulfiller()
    result = await gw.fulfill(
        db=cast(Any, None),
        order=cast(Any, None),
        item=_item(unit_price_usd=Decimal("10.00")),
        idempotency_key="ik-6b",
    )
    assert "give_amount_shortfall_units" not in result.extra_metadata


# ---------- fulfill: idempotent replay ----------


@respx.mock
async def test_repeated_fulfill_reuses_the_existing_topup() -> None:
    """Same custom_id ⇒ Waxpeer returns the original; we must not treat the
    replay as a second delivery."""
    route = respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200,
            json=_topup_json(
                topup_id=999, custom_id="ik-7", status="completed", amount=5000, give_amount=5000
            ),
        )
    )
    gw = WaxpeerFulfiller()
    first = await gw.fulfill(
        db=cast(Any, None),
        order=cast(Any, None),
        item=_item(unit_price_usd=Decimal("5.00")),
        idempotency_key="ik-7",
    )
    second = await gw.fulfill(
        db=cast(Any, None),
        order=cast(Any, None),
        item=_item(unit_price_usd=Decimal("5.00")),
        idempotency_key="ik-7",
    )
    assert route.call_count == 2  # both calls hit the (mocked) supplier...
    assert first.outcome == second.outcome == "succeeded"
    assert first.external_order_id == second.external_order_id == "ik-7"
    assert first.artifact == second.artifact  # ...but resolve to the same topup


# ---------- fulfill: guards ----------


async def test_unavailable_without_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """No key configured ⇒ available is False and fulfill raises FulfillerError."""
    monkeypatch.setenv("WAXPEER_API_KEY", "")
    cfg.get_settings.cache_clear()
    try:
        gw = WaxpeerFulfiller()
        assert gw.available is False
        with pytest.raises(FulfillerError, match="not configured"):
            await gw.fulfill(
                db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="ik-8"
            )
    finally:
        cfg.get_settings.cache_clear()


async def test_fulfill_requires_steam_login() -> None:
    gw = WaxpeerFulfiller()
    with pytest.raises(FulfillerError, match="steam_login"):
        await gw.fulfill(
            db=cast(Any, None),
            order=cast(Any, None),
            item=_item(steam_login=None),
            idempotency_key="ik-9",
        )


@respx.mock
async def test_fulfill_wraps_a_waxpeer_refusal() -> None:
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "insufficient balance"})
    )
    gw = WaxpeerFulfiller()
    with pytest.raises(FulfillerError, match="waxpeer"):
        await gw.fulfill(
            db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="ik-10"
        )


@respx.mock
async def test_fulfill_wraps_a_transport_failure() -> None:
    respx.post(f"{BASE}/steam-topup").mock(side_effect=httpx.ConnectError("boom"))
    gw = WaxpeerFulfiller()
    with pytest.raises(FulfillerError, match="unreachable"):
        await gw.fulfill(
            db=cast(Any, None), order=cast(Any, None), item=_item(), idempotency_key="ik-11"
        )


# ---------- check_status ----------


@respx.mock
async def test_check_status_completed_maps_to_succeeded_with_receipt() -> None:
    respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200, json=_topup_json(status="completed", amount=3000, give_amount=3000)
        )
    )
    gw = WaxpeerFulfiller()
    db = cast(Any, _FakeDB(_item(unit_price_usd=Decimal("3.00"))))
    status = await gw.check_status(db=db, task=_task(external_order_id="ik-12"))
    assert status.outcome == "succeeded"
    assert status.artifact_kind == "topup_receipt"
    assert status.error is None


@pytest.mark.parametrize("raw_status", ["created", "sending", "unknown_future_status"])
@respx.mock
async def test_check_status_in_flight_statuses_stay_in_progress(raw_status: str) -> None:
    respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json=_topup_json(status=raw_status))
    )
    gw = WaxpeerFulfiller()
    db = cast(Any, _FakeDB(_item()))
    status = await gw.check_status(db=db, task=_task(external_order_id="ik-13"))
    assert status.outcome == "in_progress"
    assert status.artifact is None


@respx.mock
async def test_check_status_canceled_says_supplier_refunded() -> None:
    respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json=_topup_json(status="canceled"))
    )
    gw = WaxpeerFulfiller()
    db = cast(Any, _FakeDB(_item()))
    status = await gw.check_status(db=db, task=_task(external_order_id="ik-14"))
    assert status.outcome == "failed"
    assert status.error is not None
    assert "refund" in status.error.lower()


@respx.mock
async def test_check_status_error_flags_reconciliation() -> None:
    respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json=_topup_json(status="error"))
    )
    gw = WaxpeerFulfiller()
    db = cast(Any, _FakeDB(_item()))
    status = await gw.check_status(db=db, task=_task(external_order_id="ik-15"))
    assert status.outcome == "failed"
    assert status.error is not None
    assert "reconcil" in status.error.lower()


async def test_check_status_requires_external_order_id() -> None:
    gw = WaxpeerFulfiller()
    with pytest.raises(FulfillerError, match="custom_id"):
        await gw.check_status(db=cast(Any, None), task=_task(external_order_id=None))


async def test_check_status_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAXPEER_API_KEY", "")
    cfg.get_settings.cache_clear()
    try:
        gw = WaxpeerFulfiller()
        with pytest.raises(FulfillerError, match="not configured"):
            await gw.check_status(db=cast(Any, None), task=_task(external_order_id="ik-16"))
    finally:
        cfg.get_settings.cache_clear()


@respx.mock
async def test_check_status_wraps_a_waxpeer_refusal() -> None:
    respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "not found"})
    )
    gw = WaxpeerFulfiller()
    db = cast(Any, _FakeDB(_item()))
    with pytest.raises(FulfillerError, match="waxpeer"):
        await gw.check_status(db=db, task=_task(external_order_id="ik-17"))


@respx.mock
async def test_check_status_wraps_a_transport_failure() -> None:
    respx.get(f"{BASE}/steam-topup").mock(side_effect=httpx.ConnectError("boom"))
    gw = WaxpeerFulfiller()
    db = cast(Any, _FakeDB(_item()))
    with pytest.raises(FulfillerError, match="unreachable"):
        await gw.check_status(db=db, task=_task(external_order_id="ik-18"))


# ---------- cancel ----------


async def test_cancel_raises_not_integrated() -> None:
    gw = WaxpeerFulfiller()
    with pytest.raises(FulfillerNotIntegratedError):
        await gw.cancel(db=cast(Any, None), task=cast(Any, None))


# ---------- has_balance ----------


@respx.mock
async def test_has_balance_true_when_wallet_covers_it() -> None:
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"success": True, "user": {"wallet": 10000}})
    )
    gw = WaxpeerFulfiller()
    assert await gw.has_balance(5000) is True


@respx.mock
async def test_has_balance_false_when_wallet_is_short() -> None:
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"success": True, "user": {"wallet": 100}})
    )
    gw = WaxpeerFulfiller()
    assert await gw.has_balance(5000) is False


@respx.mock
async def test_has_balance_false_on_transport_error() -> None:
    """An unreachable supplier is not a sellable one — this must never raise."""
    respx.get(f"{BASE}/user").mock(side_effect=httpx.ConnectError("boom"))
    gw = WaxpeerFulfiller()
    assert await gw.has_balance(1) is False


@respx.mock
async def test_has_balance_false_on_api_error() -> None:
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "nope"})
    )
    gw = WaxpeerFulfiller()
    assert await gw.has_balance(1) is False


# ---------- injected client (constructor override) ----------


async def test_constructor_accepts_an_injected_client() -> None:
    """Mirrors G2bFulfiller's pattern: a client can be injected for tests
    without touching global settings for the transport itself."""
    client = WaxpeerClient(api_key=API_KEY, base_url=BASE, timeout_seconds=5.0)
    gw = WaxpeerFulfiller(client=client)
    assert gw._client() is client
