"""Recorded Waxpeer shapes — taken from https://api.waxpeer.com/docs/json.

``get_balance_units`` reads the balance from ``user.wallet`` only. This
shape (``{"success": true, "user": {"wallet": <int>, ...}}``) has been
confirmed against the live API with a real key — no fallback shapes are
accepted; a response missing ``user.wallet`` raises ``WaxpeerError``.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.modules.fulfillment.suppliers.waxpeer_client import (
    WaxpeerClient,
    WaxpeerError,
    WaxpeerUnavailableError,
)

BASE = "https://api.waxpeer.test/v1"
API_KEY = "k"


def _client() -> WaxpeerClient:
    return WaxpeerClient(api_key=API_KEY, base_url=BASE, timeout_seconds=5.0)


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
async def test_validate_login_raises_when_the_body_carries_no_verdict() -> None:
    """A 200 with no boolean ``valid`` is "we could not check", not "invalid".

    ``bool(body.get("valid", False))`` used to read a missing or renamed field
    as a refusal, which ``integrations.player_check`` then reports to the
    customer as "no such Steam login". Raising makes an unreadable answer
    degrade to ``status="error"`` instead — the same rule
    ``get_balance_units`` applies to ``user.wallet``.
    """
    respx.get(f"{BASE}/steam-topup/validate").mock(
        return_value=httpx.Response(200, json={"success": True, "msg": "ok"})
    )
    with pytest.raises(WaxpeerError):
        await _client().validate_login("gaben")


@respx.mock
async def test_validate_login_raises_on_a_non_boolean_verdict() -> None:
    """A string ``"true"`` is a shape change, and truthy — the worst kind."""
    respx.get(f"{BASE}/steam-topup/validate").mock(
        return_value=httpx.Response(200, json={"success": True, "valid": "true"})
    )
    with pytest.raises(WaxpeerError):
        await _client().validate_login("gaben")


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
async def test_create_topup_failure_carries_raw_body() -> None:
    # WaxpeerError.body must carry the raw payload — the fulfiller (a later
    # task) needs to re-parse it, the same way G2bError.body is re-parsed by
    # g2b_client._verdict_or_none.
    respx.post(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "not enough balance"})
    )
    with pytest.raises(WaxpeerError) as exc:
        await _client().create_topup(steam_login="gaben", amount_units=5000, custom_id="c1")
    assert exc.value.body != ""
    assert "not enough balance" in exc.value.body


@respx.mock
async def test_request_sends_the_configured_api_key() -> None:
    route = respx.get(f"{BASE}/steam-topup/validate").mock(
        return_value=httpx.Response(200, json={"success": True, "valid": True})
    )
    await _client().validate_login("gaben")
    assert route.calls.last.request.url.params["api"] == API_KEY


@respx.mock
async def test_request_raises_waxpeer_error_on_http_error_status() -> None:
    respx.get(f"{BASE}/steam-topup/validate").mock(
        return_value=httpx.Response(503, text="service unavailable")
    )
    with pytest.raises(WaxpeerError) as exc:
        await _client().validate_login("gaben")
    assert exc.value.status == 503
    assert "service unavailable" in exc.value.body


@respx.mock
async def test_request_raises_waxpeer_unavailable_on_transport_failure() -> None:
    respx.get(f"{BASE}/steam-topup/validate").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(WaxpeerUnavailableError):
        await _client().validate_login("gaben")


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
async def test_get_topup_maps_unrecognised_status_to_unknown() -> None:
    # A status Waxpeer might add later must never be silently read as an
    # existing status: "completed" would mark undelivered goods delivered,
    # "canceled" would trigger a refund that never happened.
    respx.get(f"{BASE}/steam-topup").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "topup": {
                    "id": 1,
                    "custom_id": "c1",
                    "status": "refunded",
                    "amount": 1000,
                    "give_amount": 1000,
                    "steam_login": "gaben",
                },
            },
        )
    )
    topup = await _client().get_topup(custom_id="c1")
    assert topup.status == "unknown"


@respx.mock
async def test_get_balance_units_reads_user_wallet() -> None:
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"success": True, "user": {"wallet": 123456}})
    )
    assert await _client().get_balance_units() == 123456


@respx.mock
async def test_get_balance_units_raises_when_user_wallet_missing() -> None:
    respx.get(f"{BASE}/user").mock(
        return_value=httpx.Response(200, json={"success": True, "user": {"id": 1}})
    )
    with pytest.raises(WaxpeerError) as exc:
        await _client().get_balance_units()
    assert exc.value.body != ""
    assert "success" in exc.value.body
    assert "user" in exc.value.body
