"""Recorded Waxpeer catalogue shapes: the CSV snapshot and ``/v1/prices``.

The snapshot is consumed as a stream and must never be materialised; these
tests feed it line by line through respx and assert on the parsed rows.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerClient,
    WaxpeerError,
    WaxpeerRateLimitedError,
)

BASE = "https://api.waxpeer.test/v1"
HOST = "https://api.waxpeer.test"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"


def _client() -> WaxpeerClient:
    return WaxpeerClient(api_key="k", base_url=BASE, timeout_seconds=5.0)


@respx.mock
async def test_snapshot_rows_are_parsed_from_csv() -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(
        return_value=httpx.Response(
            200,
            content=(FIXTURES / "snapshot.csv").read_bytes(),
            headers={"content-type": "text/csv; charset=utf-8"},
        )
    )
    rows = [row async for row in _client().iter_snapshot_rows()]
    assert len(rows) == 6
    assert rows[0].item_id == 53857957789
    assert rows[0].price_units == 27867
    assert rows[0].auto is True
    assert rows[2].auto is False
    assert rows[4].name == 'Sticker | Say "GG" (Holo)'
    sent = respx.calls.last.request
    assert sent.url.params["format"] == "csv"
    assert sent.url.params["api"] == "k"
    assert "include_hold" not in sent.url.params


@respx.mock
async def test_snapshot_503_raises() -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(return_value=httpx.Response(503, text="not ready"))
    with pytest.raises(WaxpeerError):
        _ = [row async for row in _client().iter_snapshot_rows()]


@respx.mock
async def test_snapshot_429_is_rate_limited() -> None:
    respx.get(f"{HOST}/v1/prices/snapshot").mock(
        return_value=httpx.Response(429, text="busy", headers={"Retry-After": "1"})
    )
    with pytest.raises(WaxpeerRateLimitedError) as exc:
        _ = [row async for row in _client().iter_snapshot_rows()]
    assert exc.value.retry_after_ms == 1000


@respx.mock
async def test_prices_returns_items() -> None:
    respx.get(f"{HOST}/v1/prices").mock(
        return_value=httpx.Response(200, content=(FIXTURES / "prices.json").read_bytes())
    )
    items = await _client().prices()
    assert len(items) == 4
    assert items[0]["type"] == "Rifles"
    assert respx.calls.last.request.url.params["minified"] == "0"


@respx.mock
async def test_search_listings_asks_for_delivery_details_and_never_hold() -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(200, content=(FIXTURES / "search_v2.json").read_bytes())
    )
    items = await _client().search_listings(["AK-47 | Redline (Field-Tested)"])
    assert len(items["AK-47 | Redline (Field-Tested)"]) == 3
    params = respx.calls.last.request.url.params
    assert params["delivery_details"] == "1"
    assert params["minified"] == "0"
    assert params.get_list("name") == ["AK-47 | Redline (Field-Tested)"]
    assert "include_hold" not in params


@respx.mock
async def test_search_listings_429_is_rate_limited() -> None:
    respx.get(f"{HOST}/v2/search-items-by-name").mock(
        return_value=httpx.Response(
            429, json={"success": False, "msg": "Too many", "msBeforeNext": 2500}
        )
    )
    with pytest.raises(WaxpeerRateLimitedError) as exc:
        await _client().search_listings(["x"])
    assert exc.value.retry_after_ms == 2500
