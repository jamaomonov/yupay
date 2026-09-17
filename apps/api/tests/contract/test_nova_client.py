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

import json
from decimal import Decimal

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


@respx.mock
async def test_offers_are_asked_for_by_category() -> None:
    """The category travels as a query param, and the body comes back whole.

    Untested until now, and it is one of the two shapes the mapping seed and
    the fulfiller are built on: `offer_id` + `category_id` is the pair their
    order endpoint requires.
    """
    route = respx.get(f"{BASE}/api/v2/topups/offers").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "kind": "topup",
                "category_id": "mobile_legends_ru",
                "name": "Mobile Legends (RU)",
                "offers": [
                    {"offer_id": "275_diamonds", "name": "275 Diamonds", "price_usd": "4.720152"}
                ],
                "fields": [
                    {"key": "player_id", "label": "Player ID", "type": "text"},
                    {"key": "server_id", "label": "Server ID", "type": "text"},
                ],
            },
        )
    )
    body = await _client().get_offers("mobile_legends_ru")
    assert route.calls.last.request.url.params["category_id"] == "mobile_legends_ru"
    assert body["offers"][0]["offer_id"] == "275_diamonds"
    # Their ORDER field key is `server_id`; their VALIDATE field key is
    # `zone_id`. Crossing the two is silent, so the shape is pinned here.
    assert [f["key"] for f in body["fields"]] == ["player_id", "server_id"]


@respx.mock
async def test_one_order_is_fetched_by_its_public_id_and_unwrapped() -> None:
    respx.get(f"{BASE}/api/v2/orders/ord_1").mock(
        return_value=httpx.Response(
            200, json={"ok": True, "order": {"id": "ord_1", "status": "completed"}}
        )
    )
    assert await _client().get_order("ord_1") == {"id": "ord_1", "status": "completed"}


@respx.mock
async def test_an_order_response_without_an_order_is_an_empty_dict() -> None:
    """Their order object is untyped in their own spec, so the client refuses
    to hand a non-dict to the fulfiller — which reads a status out of it."""
    respx.get(f"{BASE}/api/v2/orders/ord_1").mock(
        return_value=httpx.Response(200, json={"ok": True, "order": None})
    )
    assert await _client().get_order("ord_1") == {}


@respx.mock
async def test_a_real_refusal_keeps_its_sentence_not_its_status_name() -> None:
    """Their live error envelope is not the one their OpenAPI documents.

    Observed on 2026-09-17: a reused Idempotency-Key answers
    `{"message": "This Idempotency-Key was already used for a purchase…",
      "error": "Conflict", "statusCode": 409}` — no `ok`, and `error` holding
    the status name rather than the reason. Reading `error` first would put the
    word "Conflict" in `task.last_error` and throw away the only sentence that
    tells an operator what happened.
    """
    respx.post(f"{BASE}/api/v2/topups/order").mock(
        return_value=httpx.Response(
            409,
            json={
                "message": (
                    "This Idempotency-Key was already used for a purchase. "
                    "Create a new key for a new purchase."
                ),
                "error": "Conflict",
                "statusCode": 409,
            },
        )
    )
    with pytest.raises(NovaError) as excinfo:
        await _client().create_topup_order(
            category_id="pubg_mobile_auto",
            offer_id="60_uc",
            fields={"player_id": "1"},
            idempotency_key="used-before",
        )
    assert excinfo.value.status == 409
    assert "Idempotency-Key was already used" in str(excinfo.value)


@respx.mock
async def test_a_steam_order_is_a_different_endpoint_and_answers_201() -> None:
    """Their Steam top-up is not their games top-up: no category, no offer, a
    login and an amount — and a `201`, where the games one answers `200`."""
    route = respx.post(f"{BASE}/api/v2/steam-topup/order").mock(
        return_value=httpx.Response(
            201,
            json={
                "ok": True,
                "order": {"id": "ord-9", "status": "created"},
                "novaDebit": {"amountUsd": "9.80", "balanceUsd": "90.20"},
            },
        )
    )
    order = await _client().create_steam_order(
        steam_login="someone", amount_usd=Decimal("10"), idempotency_key="task-7"
    )
    sent = json.loads(route.calls.last.request.content)
    assert sent == {"steamLogin": "someone", "currency": "USD", "amount": "10.00"}
    assert route.calls.last.request.headers["Idempotency-Key"] == "task-7"
    assert order["id"] == "ord-9"
    # What we were charged is theirs to state and ours to record: it arrives
    # beside the order, not inside it, and one shape has to answer it.
    assert order["chargedUsd"] == "9.80"


@respx.mock
async def test_a_steam_amount_carries_at_most_two_decimals() -> None:
    """Their schema refuses more, and a request refused for a formatting
    reason is a customer waiting on nothing."""
    route = respx.post(f"{BASE}/api/v2/steam-topup/order").mock(
        return_value=httpx.Response(201, json={"ok": True, "order": {"id": "ord-9"}})
    )
    await _client().create_steam_order(
        steam_login="someone", amount_usd=Decimal("10.005"), idempotency_key="k"
    )
    assert json.loads(route.calls.last.request.content)["amount"] == "10.01"


@respx.mock
async def test_a_steam_plan_refusal_keeps_its_sentence() -> None:
    respx.post(f"{BASE}/api/v2/steam-topup/order").mock(
        return_value=httpx.Response(
            400,
            json={
                "ok": False,
                "error": "plan does not allow this amount",
                "availablePlans": ["silver", "gold"],
                "balanceUsd": "9.10",
            },
        )
    )
    with pytest.raises(NovaError) as excinfo:
        await _client().create_steam_order(
            steam_login="someone", amount_usd=Decimal("500"), idempotency_key="k"
        )
    assert excinfo.value.status == 400
    assert "plan does not allow" in str(excinfo.value)


@respx.mock
async def test_a_steam_create_without_an_order_is_an_empty_dict() -> None:
    """The same guard `get_order` has, shared through `_order_with_debit`:
    their order object is untyped, so a create that answers `ok` with no
    `order` at all must not hand the fulfiller something to crash on."""
    respx.post(f"{BASE}/api/v2/steam-topup/order").mock(
        return_value=httpx.Response(201, json={"ok": True})
    )
    order = await _client().create_steam_order(
        steam_login="someone", amount_usd=Decimal("10"), idempotency_key="k"
    )
    assert order == {}


@respx.mock
async def test_the_documented_envelope_still_works() -> None:
    """The shape their OpenAPI describes has to keep working too — it is what
    their 403 for a blocked account uses, and `error` is the only text there."""
    respx.get(f"{BASE}/api/v2/balance").mock(
        return_value=httpx.Response(
            403, json={"ok": False, "error": "subscription inactive", "code": "x"}
        )
    )
    with pytest.raises(NovaError) as excinfo:
        await _client().get_balance()
    assert "subscription inactive" in str(excinfo.value)


@respx.mock
async def test_a_games_create_folds_its_debit_in_too() -> None:
    """The games path returns through the same helper as the Steam one.

    For a game the debit and the price are the same number, so folding it in
    changes nothing an operator would notice — which is exactly why it needs a
    test: nothing else would catch the day their games envelope starts
    reporting a charge that differs from the price.
    """
    respx.post(f"{BASE}/api/v2/topups/order").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "order": {"id": "ord-1", "status": "created", "price_usd": "0.901476"},
                "novaDebit": {"amountUsd": "0.901476", "balanceUsd": "9.098524"},
            },
        )
    )
    order = await _client().create_topup_order(
        category_id="pubg_mobile_auto",
        offer_id="60_uc",
        fields={"player_id": "1"},
        idempotency_key="k",
    )
    assert order["chargedUsd"] == "0.901476"


@respx.mock
async def test_an_order_without_a_debit_gains_no_charge_key() -> None:
    """Absent is not zero, and it is not null either.

    A `chargedUsd: None` would reach `_charged_usd`, which tests `not in (None,
    "")` — so it would still be read as "they said nothing". But it would also
    travel into `supplier_charged_usd` handling as a key that exists, and the
    saga's rule is that a cost is recorded only when a supplier states one.
    """
    respx.post(f"{BASE}/api/v2/topups/order").mock(
        return_value=httpx.Response(200, json={"ok": True, "order": {"id": "ord-1"}})
    )
    order = await _client().create_topup_order(
        category_id="pubg_mobile_auto",
        offer_id="60_uc",
        fields={"player_id": "1"},
        idempotency_key="k",
    )
    assert "chargedUsd" not in order
