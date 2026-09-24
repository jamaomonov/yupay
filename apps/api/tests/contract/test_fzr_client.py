"""Wire-format contract for the FazerCards client.

Every fixture below is the shape their live API or their v2 documentation
gave on 2026-09-24 (api.fzr.cards, key held out of the repo). The protocol
itself is NOVA's — ``test_nova_client`` pins the paging, the two error
envelopes and the ``offers``-not-``items`` quirk once, and re-pinning them
here would test the shared client twice.

What this file is for is the part that is **FazerCards' own**, and every case
is one where carrying a NOVA assumption across would be wrong:

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
