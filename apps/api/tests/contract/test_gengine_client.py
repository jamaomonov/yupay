"""Wire-format contract for the G-Engine client.

Every fixture below is the shape the live v2.1 API actually returned when the
integration was written (api.g-engine.net, key held out of the repo). The point
is to pin the two things that are easy to get wrong and impossible to notice
until an order is lost:

* the API uses **two response envelopes** — ``{success, message, data}`` for
  ``/users/balance`` and ``/shop/*``, the bare object for ``/recharge/*``;
* a refusal arrives as **HTTP 200 with ``success: false``**, so the status code
  alone never says whether a call worked.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers.gengine_client import (
    GEngineClient,
    GEngineError,
    GEngineUnavailableError,
)

pytestmark = pytest.mark.asyncio

BASE = "https://api.g-engine.net/v2.1"


def _client() -> GEngineClient:
    return GEngineClient(api_key="test-key", base_url=BASE, timeout_seconds=5)


@respx.mock
async def test_health_reports_the_key_is_good() -> None:
    route = respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, json={"status": "Ok"})
    )
    assert await _client().health() == {"status": "Ok"}
    # The key travels in a header, never a query string — a URL lands in proxy
    # logs and browser history, a header does not.
    assert route.calls.last.request.headers["X-API-Key"] == "test-key"


@respx.mock
async def test_balance_is_unwrapped_from_the_success_envelope() -> None:
    respx.get(f"{BASE}/users/balance").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {"balance": 54.05, "cashback": 0.0, "currency": "USD"},
            },
        )
    )
    assert await _client().get_balance() == {
        "balance": 54.05,
        "cashback": 0.0,
        "currency": "USD",
    }


@respx.mock
async def test_a_refusal_on_http_200_is_still_a_failure() -> None:
    # Verbatim from the live API when `limit` exceeds its cap.
    respx.get(f"{BASE}/users/balance").mock(
        return_value=httpx.Response(
            200,
            json={"success": False, "message": "Input should be less than or equal to 100"},
        )
    )
    with pytest.raises(GEngineError, match="less than or equal to 100"):
        await _client().get_balance()


@respx.mock
async def test_recharge_services_come_back_without_an_envelope() -> None:
    respx.get(f"{BASE}/recharge/services").mock(
        return_value=httpx.Response(
            200,
            json={
                "total": 37,
                "limit": 100,
                "offset": 0,
                "items": [
                    {
                        "id": 5,
                        "name": "Mobile Legends Bang Bang (Russia)",
                        "type": "fixed",
                        "params": [
                            {"param_key": "Account", "param_type": "String"},
                            {"param_key": "Region", "param_type": "String"},
                        ],
                        "denominations": [
                            {"id": 1, "name": "32 + 3 Diamonds", "value": "35", "price": 0.6018}
                        ],
                    }
                ],
            },
        )
    )
    services = await _client().list_recharge_services()
    assert [s["id"] for s in services] == [5]
    assert [p["param_key"] for p in services[0]["params"]] == ["Account", "Region"]


@respx.mock
async def test_the_page_size_is_capped_before_the_request_not_after_a_422() -> None:
    route = respx.get(f"{BASE}/recharge/services").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    await _client().list_recharge_services(limit=500)
    assert route.calls.last.request.url.params["limit"] == "100"


@respx.mock
async def test_creating_an_order_sends_our_uuid_and_the_params_as_a_list() -> None:
    route = respx.post(f"{BASE}/recharge/orders/5").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 9001,
                "uuid": "our-correlation-id",
                "status": "pending",
                "price": 0.6018,
                "currency": "USD",
                "is_refunded": False,
            },
        )
    )
    order = await _client().create_recharge_order(
        service_id=5,
        params={"Account": "1313232551", "Region": "6618"},
        denomination_id=1,
        uuid="our-correlation-id",
    )
    assert (order.id, order.status, order.uuid) == (9001, "pending", "our-correlation-id")

    sent = json.loads(route.calls.last.request.read())
    # The API takes params as a list of key/value objects, not a mapping — the
    # one shape difference that would silently drop a server id.
    assert sent["params"] == [
        {"param_key": "Account", "param_value": "1313232551"},
        {"param_key": "Region", "param_value": "6618"},
    ]
    assert sent["denomination_id"] == 1
    assert sent["uuid"] == "our-correlation-id"


@respx.mock
async def test_an_order_can_be_recovered_by_the_uuid_we_minted() -> None:
    """The create call's response can be lost to a timeout; the sale must not
    turn into a second order."""
    respx.get(f"{BASE}/recharge/orders/our-correlation-id/uuid").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 9001,
                "uuid": "our-correlation-id",
                "status": "verified",
                "price": 0.6018,
                "currency": "USD",
                "is_refunded": False,
            },
        )
    )
    order = await _client().get_recharge_order_by_uuid("our-correlation-id")
    assert order.id == 9001
    assert order.status == "verified"


@respx.mock
async def test_a_network_fault_is_distinct_from_a_refusal() -> None:
    # Nothing was decided upstream, so the caller may retry — unlike a refusal,
    # which is the supplier's answer.
    respx.get(f"{BASE}/health").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(GEngineUnavailableError):
        await _client().health()


@respx.mock
async def test_an_http_error_carries_its_body_for_diagnosis() -> None:
    respx.post(f"{BASE}/recharge/orders/5").mock(
        return_value=httpx.Response(422, json={"detail": "denomination_id required"})
    )
    with pytest.raises(GEngineError) as exc:
        await _client().create_recharge_order(service_id=5, params={"Account": "1"})
    assert exc.value.status == 422
    assert "denomination_id" in exc.value.body


@respx.mock
async def test_a_response_without_an_order_is_an_error_not_a_blank_order() -> None:
    """A silently empty order would look like a successful sale with no id to
    reconcile against."""
    respx.post(f"{BASE}/recharge/orders/5").mock(return_value=httpx.Response(200, json={}))
    with pytest.raises(GEngineError, match="no order"):
        await _client().create_recharge_order(service_id=5, params={"Account": "1"})


# ---------- shop: gift codes and keys ----------


@respx.mock
async def test_shop_codes_are_flattened_out_of_a_three_level_nesting() -> None:
    """The codes sit at ``products[].denominations[].items[].activation_code``.
    Every caller wants the codes; none of them want the tree."""
    respx.post(f"{BASE}/shop/orders/7001/pay").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {
                    "id": 7001,
                    "status": "shipped",
                    "is_refunded": False,
                    "price": 3.5,
                    "created_at": "2026-08-17T00:00:00Z",
                    "products": [
                        {
                            "id": 140,
                            "name": "Standoff 2 Gold",
                            "denominations": [
                                {
                                    "id": 555,
                                    "name": "500 Gold",
                                    "items": [
                                        {"id": 1, "activation_code": "AAA-111", "price": 1.75},
                                        {"id": 2, "activation_code": "BBB-222", "price": 1.75},
                                    ],
                                }
                            ],
                        }
                    ],
                },
            },
        )
    )
    order = await _client().pay_shop_order(7001)
    assert order.codes == ["AAA-111", "BBB-222"]
    assert order.status == "shipped"


@respx.mock
async def test_reserving_sends_the_denomination_id_and_quantity() -> None:
    route = respx.post(f"{BASE}/shop/orders").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {
                    "id": 7001,
                    "status": "pending",
                    "is_refunded": False,
                    "price": 3.5,
                    "products": [],
                },
            },
        )
    )
    order = await _client().create_shop_order(denomination_id=555, quantity=2)

    assert (order.id, order.status, order.codes) == (7001, "pending", [])
    assert json.loads(route.calls.last.request.read()) == {"items": [{"id": 555, "quantity": 2}]}


@respx.mock
async def test_shop_denominations_report_stock() -> None:
    # Stock is what lets us stop offering a SKU before a customer pays for
    # something the supplier cannot hand over.
    respx.get(f"{BASE}/shop/denominations/140").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": [
                    {"id": 555, "name": "500 Gold", "value": "500", "price": 1.75, "stock": 42}
                ],
            },
        )
    )
    denoms = await _client().list_shop_denominations(140)
    assert denoms[0]["stock"] == 42


@respx.mock
async def test_a_shop_response_without_an_order_is_an_error() -> None:
    respx.post(f"{BASE}/shop/orders").mock(
        return_value=httpx.Response(200, json={"success": True, "message": "", "data": {}})
    )
    with pytest.raises(GEngineError, match="no shop order"):
        await _client().create_shop_order(denomination_id=555, quantity=1)


@respx.mock
async def test_paying_a_recharge_order_returns_its_new_state() -> None:
    respx.post(f"{BASE}/recharge/orders/9001/pay").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 9001,
                "uuid": "u",
                "status": "shipped",
                "price": 0.77,
                "currency": "USD",
                "is_refunded": False,
            },
        )
    )
    order = await _client().pay_recharge_order(9001)
    assert (order.id, order.status) == (9001, "shipped")


@respx.mock
async def test_an_order_can_be_read_back_by_its_supplier_id() -> None:
    respx.get(f"{BASE}/recharge/orders/9001").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 9001,
                "uuid": "u",
                "status": "verified",
                "price": 0.77,
                "currency": "USD",
                "is_refunded": False,
            },
        )
    )
    assert (await _client().get_recharge_order(9001)).status == "verified"


@respx.mock
async def test_shop_products_are_unwrapped_and_paged() -> None:
    route = respx.get(f"{BASE}/shop/products").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {"total": 1, "items": [{"id": 140, "name": "Standoff 2"}]},
            },
        )
    )
    products = await _client().list_shop_products(limit=500)
    assert [p["id"] for p in products] == [140]
    # Same server-side cap as the recharge catalogue: asking for more is a
    # refusal, not a clamp.
    assert route.calls.last.request.url.params["limit"] == "100"


@respx.mock
async def test_a_shop_order_can_be_read_back_before_paying() -> None:
    """The poller's entry point when a reservation was made but the pay call's
    answer was lost."""
    respx.get(f"{BASE}/shop/orders/7001").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {
                    "id": 7001,
                    "status": "pending",
                    "is_refunded": False,
                    "price": 3.5,
                    "products": [],
                },
            },
        )
    )
    order = await _client().get_shop_order(7001)
    assert (order.status, order.codes) == ("pending", [])


@respx.mock
async def test_a_non_json_body_is_named_rather_than_crashing() -> None:
    # An HTML error page from a proxy is the realistic case; `json()` on it
    # raises a ValueError that would surface with no hint of the cause.
    respx.get(f"{BASE}/health").mock(
        return_value=httpx.Response(200, text="<html>502 Bad Gateway</html>")
    )
    with pytest.raises(GEngineError, match="non-JSON"):
        await _client().health()


# ---------- gifts: Steam gift games ----------

_GIFT_ORDER_BODY = {
    "id": 990,
    "uuid": "ge-uuid-990",
    "steam_id": "76561198999918080",
    "invite_url": "https://steamcommunity.com/profiles/76561198999918080/",
    "region": "CIS",
    "purchase_price": 1.02,
    "status": "accepted",
    "error": None,
    "is_refunded": False,
    "created_at": "2026-09-03T10:00:00Z",
    "updated_at": "2026-09-03T10:00:00Z",
    "package": {
        "id": 55,
        "name": "Dead Cells",
        "apps": [{"id": 1, "name": "Dead Cells", "type": "game"}],
    },
}


@respx.mock
async def test_gift_apps_come_back_with_a_total() -> None:
    route = respx.get(f"{BASE}/gifts/apps").mock(
        return_value=httpx.Response(
            200, json={"total": 4241, "items": [{"id": 588650, "name": "Dead Cells"}]}
        )
    )
    items, total = await _client().list_gift_apps(limit=25, offset=0, search="dead")
    assert total == 4241
    assert items[0]["id"] == 588650
    assert route.calls.last.request.url.params["search"] == "dead"


@respx.mock
async def test_gift_search_longer_than_the_server_cap_is_truncated_not_422d() -> None:
    route = respx.get(f"{BASE}/gifts/apps").mock(
        return_value=httpx.Response(200, json={"total": 0, "items": []})
    )
    await _client().list_gift_apps(search="x" * 50)
    assert len(route.calls.last.request.url.params["search"]) == 36


@respx.mock
async def test_creating_a_gift_order_posts_the_three_fields_and_parses_the_package() -> None:
    route = respx.post(f"{BASE}/gifts/orders").mock(
        return_value=httpx.Response(200, json=_GIFT_ORDER_BODY)
    )
    order = await _client().create_gift_order(
        invite_url="https://steamcommunity.com/profiles/76561198999918080/",
        package_id=55,
        region="CIS",
    )
    sent = json.loads(route.calls.last.request.content)
    assert sent == {
        "invite_url": "https://steamcommunity.com/profiles/76561198999918080/",
        "package_id": 55,
        "region": "CIS",
    }
    assert order.id == 990
    assert order.package_id == 55
    assert order.package_name == "Dead Cells"
    assert order.status == "accepted"


@respx.mock
async def test_gift_orders_listing_unpacks_items() -> None:
    respx.get(f"{BASE}/gifts/orders").mock(
        return_value=httpx.Response(200, json={"total": 1, "items": [_GIFT_ORDER_BODY]})
    )
    orders = await _client().list_gift_orders(search="76561198999918080")
    assert [o.id for o in orders] == [990]


@respx.mock
async def test_a_gift_order_fetch_maps_refund_and_error_fields() -> None:
    body = dict(
        _GIFT_ORDER_BODY, status="refunded", is_refunded=True, error="declined by recipient"
    )
    respx.get(f"{BASE}/gifts/orders/990").mock(return_value=httpx.Response(200, json=body))
    order = await _client().get_gift_order(990)
    assert order.is_refunded is True
    assert order.error == "declined by recipient"
