"""Recorded csmarket public API shapes (probed against prod 2026-10-09, values faked)."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers.csmarket_client import (
    USER_AGENT,
    CsmarketClient,
    CsmarketError,
    CsmarketRateLimitedError,
    CsmarketUnavailableError,
    units_to_usd,
    usd_to_units,
)

BASE = "https://api.csmarket.test/api/v1/public"
TOKEN = "csm_FAKEtokenForTestsOnly"
LINK = "https://steamcommunity.com/tradeoffer/new/?partner=1&token=FAKEFAKE"


def _client() -> CsmarketClient:
    return CsmarketClient(api_key=TOKEN, base_url=BASE, timeout_seconds=5.0)


def _order(status: str = "buying", **extra: object) -> dict[str, object]:
    return {
        "order_id": "A1B2C3D4",
        "client_order_id": "task-1",
        "status": status,
        "item": {
            "item_id": "item-1",
            "slug": "ak-47-redline-field-tested",
            "market_hash_name": "AK-47 | Redline (Field-Tested)",
        },
        "price_usd": "11.530",
        "created_at": "2026-10-09T08:20:00Z",
        "trade": None,
        "refund": None,
        **extra,
    }


def test_usd_units_round_trip() -> None:
    assert usd_to_units("12.345") == 12345
    assert usd_to_units("0.005") == 5
    assert units_to_usd(12345) == "12.345"
    assert units_to_usd(5) == "0.005"
    with pytest.raises(ValueError, match="not a USD amount"):
        usd_to_units("-1")
    with pytest.raises(ValueError, match="not a USD amount"):
        usd_to_units("NaN")


@respx.mock
async def test_me_sends_bearer_and_user_agent() -> None:
    route = respx.get(f"{BASE}/me").mock(
        return_value=httpx.Response(
            200,
            json={
                "balance_usd": "250.000",
                "usd_wallet_enabled": True,
                "key": {"id": "k", "pricing_profile": "cost", "created_at": "2026-10-09T12:27:03Z"},
                "limits": {"read_per_min": 600, "orders_per_min": 30, "feed_per_min": 1},
            },
        )
    )
    me = await _client().me()
    assert me.balance_units == 250000
    assert me.usd_wallet_enabled is True
    assert me.pricing_profile == "cost"
    assert me.limits["read_per_min"] == 600
    sent = route.calls.last.request
    assert sent.headers["Authorization"] == f"Bearer {TOKEN}"
    assert sent.headers["User-Agent"] == USER_AGENT


@respx.mock
async def test_feed_pages_follow_the_cursor_and_skip_odd_rows() -> None:
    page0 = {
        "items": [
            {
                "item_id": "i1",
                "slug": "bayonet-doppler-factory-new-phase-2",
                "market_hash_name": "★ Bayonet | Doppler (Factory New)",
                "exterior": "FN",
                "price_usd": "468.620",
                "retail_price_usd": "504.550",
                "stock": 26,
                "updated_at": "2026-10-09T02:11:47.356858+00:00",
            },
            {"item_id": "broken"},
        ],
        "next_cursor": "20261009122728.1",
    }
    page1 = {
        "items": [
            {
                "item_id": "i2",
                "slug": "ak-47-redline-field-tested",
                "market_hash_name": "AK-47 | Redline (Field-Tested)",
                "exterior": "FT",
                "price_usd": "11.530",
                "stock": 102,
                "updated_at": None,
            }
        ],
        "next_cursor": None,
    }

    def answer(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=page1 if cursor else page0, headers={"ETag": '"e-gzip"'})

    respx.get(f"{BASE}/catalog").mock(side_effect=answer)
    items = [item async for item in _client().iter_catalog()]
    assert [i.item_id for i in items] == ["i1", "i2"]
    assert items[0].price_units == 468620
    assert items[0].retail_price_units == 504550
    assert items[0].stock == 26
    assert items[1].retail_price_units is None
    assert items[1].updated_at is None
    assert respx.calls[1].request.url.params["cursor"] == "20261009122728.1"


@respx.mock
async def test_feed_304_is_none() -> None:
    route = respx.get(f"{BASE}/catalog").mock(return_value=httpx.Response(304))
    assert await _client().catalog_page(etag='"e-gzip"') is None
    assert route.calls.last.request.headers["If-None-Match"] == '"e-gzip"'


@respx.mock
async def test_feed_429_carries_retry_after() -> None:
    respx.get(f"{BASE}/catalog").mock(
        return_value=httpx.Response(
            429,
            json={"status": 429, "code": "rate_limited", "detail": "slow down"},
            headers={"Retry-After": "60"},
        )
    )
    with pytest.raises(CsmarketRateLimitedError) as caught:
        await _client().catalog_page()
    assert caught.value.retry_after == 60
    assert caught.value.code == "rate_limited"


@respx.mock
async def test_offers_are_parsed() -> None:
    respx.get(f"{BASE}/catalog/i2/offers").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "offer_id": "rBGDFCIOesyZ9-DMdmHEEJA8jPyS5w6v",
                    "float": 0.337198,
                    "paint_seed": 795,
                    "stickers": [{"name": "Sticker | Foo", "slot": 1}, "junk"],
                    "price_usd": "11.530",
                    "retail_price_usd": "12.420",
                    "delivery": "instant",
                },
                {"offer_id": "", "price_usd": "1.000"},
            ],
        )
    )
    offers = await _client().offers("i2")
    assert len(offers) == 1
    offer = offers[0]
    assert offer.price_units == 11530
    assert offer.retail_price_units == 12420
    assert offer.float_value == pytest.approx(0.337198)
    assert offer.paint_seed == 795
    assert offer.stickers == [{"name": "Sticker | Foo", "image": None, "slot": 1, "wear": None}]
    assert offer.delivery == "instant"


@respx.mock
async def test_create_order_sends_the_contract() -> None:
    route = respx.post(f"{BASE}/orders").mock(return_value=httpx.Response(201, json=_order()))
    order, created = await _client().create_order(
        item_id="item-1",
        offer_id="off-1",
        max_price_units=11530,
        trade_link=LINK,
        client_order_id="task-1",
    )
    assert created is True
    assert order.status == "buying"
    assert order.price_units == 11530
    assert json.loads(route.calls.last.request.content) == {
        "item_id": "item-1",
        "offer_id": "off-1",
        "max_price_usd": "11.530",
        "trade_link": LINK,
        "client_order_id": "task-1",
    }


@respx.mock
async def test_create_order_without_offer_id_omits_it() -> None:
    route = respx.post(f"{BASE}/orders").mock(return_value=httpx.Response(201, json=_order()))
    await _client().create_order(
        item_id="item-1", offer_id=None, max_price_units=1, trade_link=LINK, client_order_id="t"
    )
    assert "offer_id" not in json.loads(route.calls.last.request.content)


@respx.mock
async def test_duplicate_client_order_id_returns_the_existing_order() -> None:
    respx.post(f"{BASE}/orders").mock(
        return_value=httpx.Response(
            409,
            json={
                "status": 409,
                "code": "duplicate_client_order_id",
                "detail": "already placed",
                "order": _order("trade_sent"),
            },
        )
    )
    order, created = await _client().create_order(
        item_id="item-1", offer_id="o", max_price_units=1, trade_link=LINK, client_order_id="task-1"
    )
    assert created is False
    assert order.status == "trade_sent"


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (402, "insufficient_balance"),
        (409, "offer_gone"),
        (409, "price_above_max"),
        (403, "usd_wallet_disabled"),
        (422, "trade_link_invalid"),
    ],
)
@respx.mock
async def test_order_refusals_raise_with_code(status: int, code: str) -> None:
    respx.post(f"{BASE}/orders").mock(
        return_value=httpx.Response(
            status, json={"status": status, "code": code, "detail": "no", "price_usd": "12.000"}
        )
    )
    with pytest.raises(CsmarketError) as caught:
        await _client().create_order(
            item_id="i", offer_id="o", max_price_units=1, trade_link=LINK, client_order_id="t"
        )
    assert caught.value.status == status
    assert caught.value.code == code
    assert caught.value.extra.get("price_usd") == "12.000"


@respx.mock
async def test_5xx_and_network_errors_are_unavailable() -> None:
    respx.post(f"{BASE}/orders").mock(return_value=httpx.Response(502, text="bad gateway"))
    with pytest.raises(CsmarketUnavailableError):
        await _client().create_order(
            item_id="i", offer_id="o", max_price_units=1, trade_link=LINK, client_order_id="t"
        )
    respx.get(f"{BASE}/orders/X").mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(CsmarketUnavailableError) as caught:
        await _client().order("X")
    assert str(caught.value)  # never an empty diagnosis


@respx.mock
async def test_order_with_trade_and_refund() -> None:
    delivered = _order(
        "delivered",
        trade={
            "offer_sent_at": "2026-10-09T08:21:29Z",
            "accepted_at": "2026-10-09T08:25:00Z",
            "release_at": "2026-10-16T08:25:00Z",
            "steam_offer_id": "7612345678",
            "seller_name": "seller",
        },
    )
    respx.get(f"{BASE}/orders/A1B2C3D4").mock(return_value=httpx.Response(200, json=delivered))
    order = await _client().order("A1B2C3D4")
    assert order.status == "delivered"
    assert order.trade is not None
    assert order.trade.steam_offer_id == "7612345678"
    assert order.trade.release_at is not None

    refunded = _order("refunded", refund={"amount_usd": "11.530", "reason": "sold_out"})
    respx.get(f"{BASE}/orders/R").mock(return_value=httpx.Response(200, json=refunded))
    order = await _client().order("R")
    assert order.refund_units == 11530
    assert order.refund_reason == "sold_out"


@respx.mock
async def test_unknown_status_is_kept_as_unknown() -> None:
    respx.get(f"{BASE}/orders/U").mock(return_value=httpx.Response(200, json=_order("held")))
    assert (await _client().order("U")).status == "unknown"


@respx.mock
async def test_order_not_found() -> None:
    respx.get(f"{BASE}/orders/N").mock(
        return_value=httpx.Response(404, json={"status": 404, "code": "order_not_found"})
    )
    with pytest.raises(CsmarketError) as caught:
        await _client().order("N")
    assert caught.value.code == "order_not_found"


@respx.mock
async def test_tradelink_check() -> None:
    route = respx.post(f"{BASE}/tradelink/check").mock(
        return_value=httpx.Response(200, json={"verdict": "bad", "reason": "invalid_link"})
    )
    assert await _client().check_tradelink(LINK) == ("bad", "invalid_link")
    assert json.loads(route.calls.last.request.content) == {"trade_link": LINK}
    respx.post(f"{BASE}/tradelink/check").mock(
        return_value=httpx.Response(200, json={"verdict": "ok", "reason": None})
    )
    assert await _client().check_tradelink(LINK) == ("ok", None)


@respx.mock
async def test_tradelink_check_odd_shape_raises() -> None:
    respx.post(f"{BASE}/tradelink/check").mock(return_value=httpx.Response(200, json={"x": 1}))
    with pytest.raises(CsmarketError):
        await _client().check_tradelink(LINK)


def test_odd_values_never_parse_as_money() -> None:
    with pytest.raises(ValueError, match="not a USD amount"):
        usd_to_units("abc")


@respx.mock
async def test_an_injected_http_client_is_used_and_configured_reads_the_key() -> None:
    respx.get(f"{BASE}/me").mock(
        return_value=httpx.Response(
            200, json={"balance_usd": "1.000", "usd_wallet_enabled": True, "key": {}}
        )
    )
    async with httpx.AsyncClient() as http:
        client = CsmarketClient(api_key=TOKEN, base_url=BASE, timeout_seconds=5.0, client=http)
        assert client.configured is True
        assert (await client.me()).balance_units == 1000
    assert CsmarketClient(api_key="", base_url=BASE, timeout_seconds=5.0).configured is False


@respx.mock
async def test_odd_feed_rows_and_dates_are_tolerated() -> None:
    respx.get(f"{BASE}/catalog").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "item_id": "i1",
                        "slug": "s",
                        "market_hash_name": "N",
                        "price_usd": "1.000",
                        "stock": 1,
                        "updated_at": "not-a-date",
                    },
                    {"item_id": "i2", "slug": "s2", "market_hash_name": "N2", "price_usd": "x"},
                ],
                "next_cursor": None,
            },
        )
    )
    page = await _client().catalog_page()
    assert page is not None
    assert [i.item_id for i in page.items] == ["i1"]
    assert page.items[0].updated_at is None


@respx.mock
async def test_odd_offers_and_stickers_are_dropped() -> None:
    respx.get(f"{BASE}/catalog/i/offers").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"offer_id": "a", "price_usd": "nope"},
                {"offer_id": "b", "price_usd": "1.000", "stickers": [{"slot": 1}]},
            ],
        )
    )
    offers = await _client().offers("i")
    assert [o.offer_id for o in offers] == ["b"]
    assert offers[0].stickers == []


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/me", {"balance_usd": "x"}),
        ("/catalog", {"items": "x"}),
        ("/catalog/i/offers", {"not": "a list"}),
        ("/orders/O", {"order_id": "O"}),
    ],
)
@respx.mock
async def test_unexpected_shapes_raise_bad_shape(path: str, body: object) -> None:
    respx.get(f"{BASE}{path}").mock(return_value=httpx.Response(200, json=body))
    client = _client()
    calls: dict[str, Callable[[], Awaitable[object]]] = {
        "/me": client.me,
        "/catalog": client.catalog_page,
        "/catalog/i/offers": lambda: client.offers("i"),
        "/orders/O": lambda: client.order("O"),
    }
    with pytest.raises(CsmarketError) as caught:
        await calls[path]()
    assert caught.value.code == "bad_shape"


# ---------- the lot check before payment (csmarket v1.2) ----------


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ({"offer_id": "o", "status": "available", "price_usd": "4.100"}, ("available", 4100)),
        ({"offer_id": "o", "status": "gone", "price_usd": None}, ("gone", None)),
        ({"offer_id": "o", "status": "unconfirmed", "price_usd": "4.000"}, ("unconfirmed", 4000)),
        ({"offer_id": "o", "status": "weird"}, ("unconfirmed", None)),
        ({"offer_id": "o", "status": "available", "price_usd": "x"}, ("available", None)),
    ],
)
@respx.mock
async def test_check_offer_reads_the_lot(body: dict[str, object], expected: object) -> None:
    route = respx.get(f"{BASE}/catalog/i1/offers/o").mock(
        return_value=httpx.Response(200, json=body)
    )
    assert await _client().check_offer("i1", "o") == expected
    assert route.calls.last.request.headers["Authorization"] == f"Bearer {TOKEN}"


@respx.mock
async def test_check_offer_404_is_gone_and_failures_are_unconfirmed() -> None:
    respx.get(f"{BASE}/catalog/i1/offers/x").mock(
        return_value=httpx.Response(404, json={"status": 404, "code": "offer_not_found"})
    )
    assert await _client().check_offer("i1", "x") == ("gone", None)
    for answer in (
        httpx.Response(401, json={"status": 401, "code": "unauthorized"}),
        httpx.Response(429, json={"status": 429, "code": "rate_limited"}),
        httpx.Response(503, text="down"),
        httpx.ReadTimeout("slow"),
    ):
        respx.get(f"{BASE}/catalog/i1/offers/y").mock(
            side_effect=answer if isinstance(answer, Exception) else None,
            return_value=None if isinstance(answer, Exception) else answer,
        )
        assert await _client().check_offer("i1", "y") == ("unconfirmed", None)
