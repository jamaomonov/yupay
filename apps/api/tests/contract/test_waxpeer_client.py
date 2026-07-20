"""Recorded Waxpeer shapes — taken from https://api.waxpeer.com/docs/json.

``get_balance_units`` is defensive about the ``GET /v1/user`` response shape:
the real payload has never been observed against the live API (only the
recorded docs shape below), so the client accepts a numeric balance under
``user.wallet``, top-level ``wallet``, or top-level ``balance`` — whichever
is present first — instead of committing to a single guessed shape. A later
task should confirm the real shape against the live API and, if it differs
from all three, extend the accepted shapes.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerClient,
    WaxpeerError,
)

BASE = "https://api.waxpeer.test/v1"


def _client() -> WaxpeerClient:
    return WaxpeerClient(api_key="k", base_url=BASE, timeout_seconds=5.0)


@respx.mock
async def test_validate_login_accepts_supported_account() -> None:
    respx.get(f"{BASE}/steam-topup/validate").mock(
        return_value=httpx.Response(200, json={"success": True, "valid": True})
    )
    valid, message = await _client().validate_login("gaben")
    assert valid is True
    assert message is None


@respx.mock
async def test_validate_login_reports_the_reason() -> None:
    respx.get(f"{BASE}/steam-topup/validate").mock(
        return_value=httpx.Response(
            200, json={"success": True, "valid": False, "msg": "account not found"}
        )
    )
    valid, message = await _client().validate_login("nobody")
    assert valid is False
    assert message == "account not found"


@respx.mock
async def test_create_topup_parses_the_topup_object() -> None:
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "msg": None,
                "topup": {
                    "id": 812345,
                    "custom_id": "order-123",
                    "status": "created",
                    "amount": 5000,
                    "give_amount": 5000,
                    "steam_login": "gaben",
                },
            },
        )
    )
    topup = await _client().create_topup(
        steam_login="gaben", amount_units=5000, custom_id="order-123"
    )
    assert topup.id == 812345
    assert topup.status == "created"
    assert topup.amount_units == 5000
    assert topup.give_amount_units == 5000


@respx.mock
async def test_create_topup_raises_on_api_level_failure() -> None:
    # HTTP 200 with success=false is how Waxpeer reports a refusal.
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "not enough balance"})
    )
    with pytest.raises(WaxpeerError) as exc:
        await _client().create_topup(steam_login="gaben", amount_units=5000, custom_id="c1")
    assert "not enough balance" in str(exc.value)


@respx.mock
async def test_get_topup_by_custom_id() -> None:
    route = respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "topup": {
                    "id": 1,
                    "custom_id": "c1",
                    "status": "completed",
                    "amount": 1000,
                    "give_amount": 1000,
                    "steam_login": "gaben",
                },
            },
        )
    )
    topup = await _client().get_topup(custom_id="c1")
    assert topup.status == "completed"
    assert route.calls.last.request.url.params["custom_id"] == "c1"


@respx.mock
async def test_get_balance_units_reads_user_wallet() -> None:
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"success": True, "user": {"wallet": 123456}})
    )
    assert await _client().get_balance_units() == 123456


@respx.mock
async def test_get_balance_units_reads_top_level_wallet() -> None:
    # Guessed fallback shape — accepted in case the balance isn't nested
    # under "user" the way the docs suggest.
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"success": True, "wallet": 654321})
    )
    assert await _client().get_balance_units() == 654321


@respx.mock
async def test_get_balance_units_reads_balance_key() -> None:
    # Guessed fallback shape — accepted in case Waxpeer names the field
    # "balance" instead of "wallet".
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"success": True, "balance": 42})
    )
    assert await _client().get_balance_units() == 42


@respx.mock
async def test_get_balance_units_prefers_user_wallet_when_multiple_present() -> None:
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "user": {"wallet": 111}, "wallet": 222, "balance": 333},
        )
    )
    assert await _client().get_balance_units() == 111


@respx.mock
async def test_get_balance_units_raises_when_no_known_shape_matches() -> None:
    respx.get(f"{BASE}/user").mock(return_value=httpx.Response(200, json={"success": True}))
    with pytest.raises(WaxpeerError):
        await _client().get_balance_units()
