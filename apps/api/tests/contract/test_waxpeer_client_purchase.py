"""Recorded Waxpeer purchase-side shapes (spike 2026-09-28, spec §8.1)."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers.waxpeer_client import WaxpeerUnavailableError
from yupay.modules.fulfillment.suppliers.waxpeer_trades import (
    WaxpeerBuyRefusedError,
    WaxpeerTradeClient,
)

BASE = "https://api.waxpeer.test/v1"
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s"


def _client() -> WaxpeerTradeClient:
    return WaxpeerTradeClient(api_key="k", base_url=BASE, timeout_seconds=5.0)


@respx.mock
async def test_a_working_trade_link_has_no_info() -> None:
    route = respx.post(f"{BASE}/check-tradelink").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "info": None,
                "msg": None,
                "link": LINK,
                "token": "LBCWEQ8s",
                "steamid32": "1039652352",
                "steamid64": "76561198999918080",
            },
        )
    )
    assert await _client().check_tradelink(LINK) is None
    assert json.loads(route.calls.last.request.content) == {"tradelink": LINK}


@respx.mock
async def test_a_broken_trade_link_returns_steams_reason() -> None:
    respx.post(f"{BASE}/check-tradelink").mock(
        return_value=httpx.Response(200, json={"success": True, "info": "Inventory is private"})
    )
    assert await _client().check_tradelink(LINK) == "Inventory is private"


@respx.mock
async def test_a_refused_trade_link_returns_the_message() -> None:
    respx.post(f"{BASE}/check-tradelink").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "Invalid tradelink"})
    )
    assert await _client().check_tradelink(LINK) == "Invalid tradelink"


@respx.mock
async def test_a_transport_failure_is_unavailable() -> None:
    respx.post(f"{BASE}/check-tradelink").mock(side_effect=httpx.ConnectTimeout("t"))
    with pytest.raises(WaxpeerUnavailableError):
        await _client().check_tradelink(LINK)


def _trade(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "id": 30717201,
        "name": "Galil AR | Grey Smoke (Field-Tested)",
        "status": 4,
        "project_id": "p-1",
        "custom_id": "c1",
        "trade_id": "9393511289",
        "done": False,
        "for_steamid64": "76561198999918080",
        "reason": None,
        "release_date": None,
        "is_released": False,
        "seller_name": "darpan6awx",
        "seller_avatar": "https://avatars.steamstatic.com/x_medium.jpg",
        "seller_steam_joined": 1730230098,
        "seller_steam_level": 12,
        "price": 6,
        "send_until": "1790636153",
        "last_updated": "1790634353",
        "counter": "564",
    }
    return {**base, **over}


@respx.mock
async def test_buying_one_listing_returns_waxpeers_id() -> None:
    route = respx.get(f"{BASE}/buy-one-p2p").mock(
        return_value=httpx.Response(200, json={"success": True, "id": 30717149, "price": 5})
    )
    bought = await _client().buy_one_p2p(
        item_id=53860909078, price_units=5, partner=1039652352, token="LBCWEQ8s", project_id="p-1"
    )
    assert (bought.id, bought.price_units) == (30717149, 5)
    params = route.calls.last.request.url.params
    assert (params["item_id"], params["price"], params["project_id"]) == ("53860909078", "5", "p-1")


@respx.mock
async def test_a_refused_buy_carries_the_new_price() -> None:
    respx.get(f"{BASE}/buy-one-p2p").mock(
        return_value=httpx.Response(
            200, json={"success": False, "msg": "Price changed", "new_price": 9}
        )
    )
    with pytest.raises(WaxpeerBuyRefusedError) as err:
        await _client().buy_one_p2p(
            item_id=1, price_units=5, partner=1, token="tttttttt", project_id="p"
        )
    assert err.value.new_price == 9
    assert "Price changed" in str(err.value)


@respx.mock
async def test_trades_are_read_by_project_id() -> None:
    route = respx.get(f"{BASE}/check-many-project-id").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "trades": [
                    _trade(),
                    _trade(project_id="p-2", release_date="2026-10-05T16:00:00.000Z"),
                    _trade(project_id="p-3", status=6, done=True, reason="Buyer failed to accept"),
                ],
            },
        )
    )
    trades = await _client().check_project_ids(["p-1", "p-2", "p-3"])
    assert [p for _, p in route.calls.last.request.url.params.multi_items() if _ == "id"] == [
        "p-1",
        "p-2",
        "p-3",
    ]
    sent, accepted, failed = trades
    assert (sent.status, sent.release_date, sent.trade_id) == (4, None, "9393511289")
    assert sent.send_until is not None
    assert sent.send_until.year == 2026
    assert accepted.release_date is not None
    assert accepted.release_date.day == 5
    assert (failed.status, failed.done, failed.reason) == (6, True, "Buyer failed to accept")
    assert sent.seller == {
        "name": "darpan6awx",
        "avatar_url": "https://avatars.steamstatic.com/x_medium.jpg",
        "level": 12,
        "joined_at": "2024-10-29T19:28:18+00:00",
    }
