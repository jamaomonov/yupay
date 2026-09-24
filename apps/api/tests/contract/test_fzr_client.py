"""Wire-format contract for the FazerCards client.

Every fixture below is the shape their live API or their v2 documentation
gave on 2026-09-24 (api.fzr.cards, key held out of the repo). The protocol is shared with NOVA, and this file pins it **again from
FazerCards' side on purpose**. ``panel_client`` serves two vendors, so an edit
made to follow one vendor's API can silently move the other; the class
hierarchy does not prevent that, a second suite that fails does. If a NOVA
change reaches the shared client, these tests are what refuse it.

The first half is the part that is **FazerCards' own**, where carrying a NOVA
assumption across would be wrong:

* their base URL and their ``fc_…`` key;
* ``subscription_inactive``, which NOVA has no equivalent of and which is the
  refusal an operator can actually fix;
* the per-category rate limit, published as 60 order creates a minute;
* ``GET /subscription``, the one endpoint with no NOVA counterpart.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers.fzr_client import (
    SUBSCRIPTION_INACTIVE,
    FzrClient,
    FzrError,
    FzrUnavailableError,
)

pytestmark = pytest.mark.asyncio

BASE = "https://api.fzr.cards"


def _client(timeout: float = 5) -> FzrClient:
    return FzrClient(api_key="fc_test", base_url=BASE, timeout_seconds=timeout)


@respx.mock
async def test_the_key_travels_in_their_header_not_the_url() -> None:
    route = respx.get(f"{BASE}/api/v2/balance").mock(
        return_value=httpx.Response(200, json={"ok": True, "balance": "0.0000", "currency": "USD"})
    )
    assert (await _client().get_balance())["balance"] == "0.0000"
    # A key in a header stays out of proxy logs and browser history.
    assert route.calls.last.request.headers["X-API-Key"] == "fc_test"


@respx.mock
async def test_a_lapsed_subscription_keeps_its_machine_code() -> None:
    """The adapter branches on this code to tell an operator to renew the
    plan. A dropped code turns that into an anonymous 403."""
    respx.post(f"{BASE}/api/v2/topups/order").mock(
        return_value=httpx.Response(
            403,
            json={
                "ok": False,
                "error": "Subscription is not active",
                "blockReason": None,
                "code": SUBSCRIPTION_INACTIVE,
            },
        )
    )
    with pytest.raises(FzrError) as excinfo:
        await _client().create_topup_order(
            category_id="free_fire_cis",
            offer_id="572_diamonds",
            fields={"player_id": "1"},
            idempotency_key="task-1",
        )

    assert excinfo.value.status == 403
    assert excinfo.value.code == SUBSCRIPTION_INACTIVE


@respx.mock
async def test_a_rate_limit_arrives_as_a_refusal_with_its_status_intact() -> None:
    """They publish 60 order creates a minute, per API key, per category of
    operation. The status is what tells the grader nothing was charged."""
    respx.post(f"{BASE}/api/v2/topups/order").mock(
        return_value=httpx.Response(
            429,
            headers={"Retry-After": "12"},
            json={"ok": False, "error": "Too many requests", "code": "rate_limited"},
        )
    )
    with pytest.raises(FzrError) as excinfo:
        await _client().create_topup_order(
            category_id="free_fire_cis",
            offer_id="572_diamonds",
            fields={"player_id": "1"},
            idempotency_key="task-1",
        )

    assert excinfo.value.status == 429


@respx.mock
async def test_an_order_create_always_carries_an_idempotency_key() -> None:
    """Their documentation says a repeat returns the original order rather
    than charging again. We have not verified that on a live duplicate, so the
    header travelling is the part that has to hold: without it a retry is
    unambiguously a second purchase."""
    route = respx.post(f"{BASE}/api/v2/topups/order").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "order": {"id": "ord-9002", "kind": "topup", "status": "processing"}},
        )
    )
    order = await _client().create_topup_order(
        category_id="free_fire_cis",
        offer_id="572_diamonds",
        fields={"player_id": "1313232551"},
        idempotency_key="task-42",
    )

    assert order["id"] == "ord-9002"
    assert route.calls.last.request.headers["Idempotency-Key"] == "task-42"


@respx.mock
async def test_a_steam_create_folds_their_debit_into_the_order() -> None:
    """What we asked them to deliver and what they charged us are different
    numbers here — their rebate is tiered — and the caller needs one key that
    answers "what were we charged" on both the create and a later GET."""
    respx.post(f"{BASE}/api/v2/steam-topup/order").mock(
        return_value=httpx.Response(
            201,
            json={
                "ok": True,
                "order": {"id": "ord-9003", "kind": "steam_topup", "status": "processing"},
                "fzrDebit": {"amountUsd": "9.6450"},
            },
        )
    )
    from decimal import Decimal

    order = await _client().create_steam_order(
        steam_login="someplayer", amount_usd=Decimal("10"), idempotency_key="task-7"
    )

    assert order["chargedUsd"] == "9.6450"


@respx.mock
async def test_the_steam_amount_is_sent_with_at_most_two_decimals() -> None:
    """Their schema requires cents for USD, and rounding is half-up so a
    fraction of a cent is never taken off what the customer bought."""
    import json
    from decimal import Decimal

    route = respx.post(f"{BASE}/api/v2/steam-topup/order").mock(
        return_value=httpx.Response(
            201, json={"ok": True, "order": {"id": "ord-1", "status": "processing"}}
        )
    )
    await _client().create_steam_order(
        steam_login="someplayer", amount_usd=Decimal("10.005"), idempotency_key="task-7"
    )

    assert json.loads(route.calls.last.request.content)["amount"] == "10.01"


@respx.mock
async def test_the_subscription_call_reports_the_plan_and_its_expiry() -> None:
    """The one endpoint with no NOVA counterpart: catalogue access here
    expires with the plan."""
    respx.get(f"{BASE}/api/v2/subscription").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "plan": "gold",
                "planExpiresAt": "2026-09-29T05:50:20.696Z",
                "planAutoRenew": False,
                "subscriptionActive": True,
                "currency": "USD",
            },
        )
    )
    body = await _client().get_subscription()

    assert body["plan"] == "gold"
    assert body["subscriptionActive"] is True


@respx.mock
async def test_a_transport_failure_is_not_a_refusal() -> None:
    """Nothing was decided upstream, which the caller grades differently from
    a refusal — and the reason survives, because every httpx transport
    exception stringifies to an empty string."""
    respx.get(f"{BASE}/api/v2/balance").mock(side_effect=httpx.ReadTimeout("", request=None))
    with pytest.raises(FzrUnavailableError) as excinfo:
        await _client().get_balance()

    assert str(excinfo.value) == "ReadTimeout"


# ---------- the shared surface, pinned again from FazerCards' side ----------
#
# These duplicate what ``test_nova_client`` asserts, and the duplication is the
# whole point. ``panel_client`` serves two vendors, so an edit made to suit one
# of them can silently move the other. The class hierarchy does not prevent
# that; a second suite that fails does.
#
# Every case below is a shape FazerCards' own documentation states, so if
# NOVA's API moves and someone follows it into the shared client, this file is
# what refuses the change.


@respx.mock
async def test_the_category_lists_are_walked_by_their_cursor() -> None:
    """``meta.next_cursor`` until it is null — 306 top-up categories live."""
    # Registered cursor-first: respx matches params as a subset, so a route
    # keyed on `limit` alone would also swallow the second request.
    respx.get(f"{BASE}/api/v2/topups", params={"limit": "100", "cursor": "c2"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "kind": "topup",
                "items": [{"category_id": "free_fire_cis", "name": "Free Fire (CIS)"}],
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
                "items": [{"category_id": "8_ball_pool", "name": "8 Ball Pool"}],
                "meta": {"total": 2, "limit": 100, "next_cursor": "c2", "has_more": True},
            },
        )
    )
    items = await _client().list_topups()

    assert [i["category_id"] for i in items] == ["8_ball_pool", "free_fire_cis"]


@respx.mock
async def test_gift_card_denominations_arrive_under_offers_not_items() -> None:
    """Every other list on this API uses ``items``; this one does not, and
    reading the wrong key returns an empty ladder rather than an error."""
    respx.get(f"{BASE}/api/v2/giftcards/cards", params={"category_id": "roblox_global"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "kind": "gift_card",
                "category_id": "roblox_global",
                "name": "Roblox (Global)",
                "offers": [
                    {
                        "card_id": "800_robux",
                        "name": "800 Robux",
                        "price_usd": "9.0000",
                        "stock": 886,
                        "min_order_quantity": 1,
                        "max_order_quantity": 10,
                    }
                ],
            },
        )
    )
    cards = await _client().list_giftcard_cards("roblox_global")

    assert [c["card_id"] for c in cards] == ["800_robux"]
    # The stock figure is what keeps a sold-out card off the shelf.
    assert cards[0]["stock"] == 886


@respx.mock
async def test_offers_carry_the_ladder_and_the_fields_the_category_asks_for() -> None:
    """The per-category ``fields`` declaration is what the adapter builds its
    order payload from — assuming a fixed rename is what refused a NOVA
    Honkai order outright."""
    respx.get(f"{BASE}/api/v2/topups/offers", params={"category_id": "free_fire_cis"}).mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "kind": "topup",
                "category_id": "free_fire_cis",
                "name": "Free Fire (CIS)",
                "offers": [
                    {"offer_id": "110_diamonds", "name": "110 Diamonds", "price_usd": "0.7809"}
                ],
                "fields": [{"key": "player_id", "label": "Player ID", "type": "text"}],
            },
        )
    )
    body = await _client().get_offers("free_fire_cis")

    assert body["offers"][0]["price_usd"] == "0.7809"
    assert [f["key"] for f in body["fields"]] == ["player_id"]


@respx.mock
async def test_one_order_is_unwrapped_from_its_envelope() -> None:
    """Their public ids look like ``ord-123``, not ``ord_123``."""
    respx.get(f"{BASE}/api/v2/orders/ord-9001").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "order": {"id": "ord-9001", "kind": "gift_card", "status": "completed"},
            },
        )
    )
    order = await _client().get_order("ord-9001")

    assert order["id"] == "ord-9001"
    assert order["status"] == "completed"


@respx.mock
async def test_the_order_list_pages_with_page_and_limit_not_a_cursor() -> None:
    """The one list on this API that is not cursor-paged. It is what adoption
    reads, so getting the shape wrong loses a paid-for order."""
    route = respx.get(f"{BASE}/api/v2/orders").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "items": [{"id": "ord-9001", "kind": "gift_card", "status": "completed"}],
                "total": 1,
                "page": 1,
                "limit": 50,
            },
        )
    )
    orders = await _client().list_orders(limit=50)

    assert [o["id"] for o in orders] == ["ord-9001"]
    assert dict(route.calls.last.request.url.params) == {"limit": "50", "page": "1"}


@respx.mock
async def test_an_unreadable_envelope_is_a_refusal_not_an_empty_answer() -> None:
    """A body without ``ok: true`` must never read as "nothing found" — on the
    order path that would be a delivered order reported as missing."""
    respx.get(f"{BASE}/api/v2/orders/ord-1").mock(return_value=httpx.Response(200, text="<html>"))
    with pytest.raises(FzrError):
        await _client().get_order("ord-1")
