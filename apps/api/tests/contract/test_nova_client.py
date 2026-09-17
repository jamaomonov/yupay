"""Wire-format contract for the NOVA client.

Every fixture below is the shape the live API returned when this integration
was written (nova-gifts.com, key held out of the repo). Two things are easy to
get wrong here and impossible to notice until an order is lost:

* every response carries ``ok``, so a refusal can arrive as an HTTP 200 with
  ``ok: false`` — the status code alone never says whether a call worked;
* the validate namespace is not the top-up namespace (``mobile_legends``
  validates, ``mobile_legends_ru`` sells), so the two never share an id.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers.nova_client import (
    NovaClient,
    NovaError,
    NovaUnavailableError,
)

pytestmark = pytest.mark.asyncio

BASE = "https://nova-gifts.com"


def _client(timeout: float = 5) -> NovaClient:
    return NovaClient(api_key="test-key", base_url=BASE, timeout_seconds=timeout)


@respx.mock
async def test_balance_carries_the_key_in_a_header() -> None:
    route = respx.get(f"{BASE}/api/v2/balance").mock(
        return_value=httpx.Response(200, json={"ok": True, "balance": "0.0000", "currency": "USD"})
    )
    assert (await _client().get_balance())["balance"] == "0.0000"
    # A key in a header stays out of proxy logs and browser history.
    assert route.calls.last.request.headers["X-API-Key"] == "test-key"


@respx.mock
async def test_ok_false_on_a_200_is_a_refusal() -> None:
    respx.get(f"{BASE}/api/v2/balance").mock(
        return_value=httpx.Response(200, json={"ok": False, "error": "nope", "code": "bad_thing"})
    )
    with pytest.raises(NovaError) as excinfo:
        await _client().get_balance()
    assert excinfo.value.code == "bad_thing"
    assert excinfo.value.status == 200


@respx.mock
async def test_blocked_account_keeps_its_code() -> None:
    respx.get(f"{BASE}/api/v2/balance").mock(
        return_value=httpx.Response(
            403,
            json={
                "ok": False,
                "error": "subscription inactive",
                "blockReason": None,
                "code": "subscription_inactive",
            },
        )
    )
    with pytest.raises(NovaError) as excinfo:
        await _client().get_balance()
    assert excinfo.value.status == 403
    assert excinfo.value.code == "subscription_inactive"


@respx.mock
async def test_topups_are_walked_by_cursor() -> None:
    # The cursor route is registered FIRST on purpose: respx matches params as
    # a subset, so a route keyed on `limit` alone would also swallow the
    # second request and the walk would never terminate.
    respx.get(f"{BASE}/api/v2/topups", params={"limit": "100", "cursor": "c2"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "kind": "topup",
                "items": [{"category_id": "pubg_mobile_auto", "name": "PUBG Mobile (Auto)"}],
                "meta": {"total": 2, "limit": 100, "next_cursor": None, "has_more": False},
            },
        )
    )
    respx.get(f"{BASE}/api/v2/topups", params={"limit": "100"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "kind": "topup",
                "items": [{"category_id": "mobile_legends_ru", "name": "Mobile Legends (RU)"}],
                "meta": {"total": 2, "limit": 100, "next_cursor": "c2", "has_more": True},
            },
        )
    )
    items = await _client().list_topups()
    assert [i["category_id"] for i in items] == ["mobile_legends_ru", "pubg_mobile_auto"]


@respx.mock
async def test_order_create_sends_the_idempotency_key_and_unwraps_the_order() -> None:
    route = respx.post(f"{BASE}/api/v2/topups/order").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "order": {"id": "ord_1", "status": "processing"}}
        )
    )
    order = await _client().create_topup_order(
        category_id="mobile_legends_ru",
        offer_id="275_diamonds",
        fields={"player_id": "1313232551", "server_id": "6618"},
        idempotency_key="task-42",
    )
    assert order == {"id": "ord_1", "status": "processing"}
    assert route.calls.last.request.headers["Idempotency-Key"] == "task-42"


@respx.mock
async def test_validate_id_maps_a_positive_verdict() -> None:
    respx.post(f"{BASE}/api/v2/topups/validate-id").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "category_id": "mobile_legends",
                "valid": True,
                "player_name": "blood moon",
                "player_id": "1313232551",
                "region": "Russia",
            },
        )
    )
    out = await _client().validate_id(
        category_id="mobile_legends", fields={"player_id": "1313232551", "zone_id": "6618"}
    )
    assert (out.valid, out.player_name, out.region) == (True, "blood moon", "Russia")


@respx.mock
async def test_validate_id_maps_a_negative_verdict() -> None:
    respx.post(f"{BASE}/api/v2/topups/validate-id").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "category_id": "pubg_mobile", "valid": False, "player_name": None},
        )
    )
    out = await _client().validate_id(category_id="pubg_mobile", fields={"player_id": "1"})
    assert out.valid is False
    assert out.player_name is None


@respx.mock
async def test_validate_id_422_is_an_error_not_a_verdict() -> None:
    respx.post(f"{BASE}/api/v2/topups/validate-id").mock(
        return_value=httpx.Response(422, json={"ok": False, "error": "could not confirm"})
    )
    with pytest.raises(NovaError):
        await _client().validate_id(category_id="pubg_mobile", fields={"player_id": "1"})


@respx.mock
async def test_steam_login_check_returns_the_boolean() -> None:
    respx.post(f"{BASE}/api/v2/steam-topup/check-login").mock(
        return_value=httpx.Response(200, json={"ok": True, "can_refill": True})
    )
    assert await _client().check_steam_login("someone") is True


@respx.mock
async def test_a_network_error_is_unavailable_not_a_refusal() -> None:
    respx.get(f"{BASE}/api/v2/balance").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(NovaUnavailableError):
        await _client().get_balance()


@respx.mock
async def test_non_json_is_a_refusal_with_the_body_kept() -> None:
    respx.get(f"{BASE}/api/v2/balance").mock(return_value=httpx.Response(502, text="<html>nginx"))
    with pytest.raises(NovaError) as excinfo:
        await _client().get_balance()
    assert "nginx" in excinfo.value.body
