"""Contract tests for :class:`G2bClient` using respx as the HTTP transport.

Doesn't touch the DB or the saga — just the wire format. Verifies that:
- Auth header + idempotency key are set.
- COMPLETED / PENDING voucher purchases are correctly mapped.
- Voucher delivery polling reads 200 / 202 / 410.
- Game order creation + status read game statuses.
- 429 is retried with backoff (we monkey-patch ``asyncio.sleep``).
- 401 stops immediately without retrying.
- Network errors → ``UpstreamUnavailableError``.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from yupay.core.errors import UpstreamUnavailableError
from yupay.modules.fulfillment.suppliers.g2b_client import (
    G2bClient,
    G2bError,
    G2bTerminalFailure,
)

pytestmark = pytest.mark.asyncio


def _client(**kwargs: Any) -> G2bClient:
    defaults: dict[str, Any] = {
        "api_key": "test-key",
        "base_url": "https://g2b.test/v1",
        "timeout_seconds": 2.0,
        "max_retries": 2,
    }
    defaults.update(kwargs)
    return G2bClient(**defaults)


@respx.mock
async def test_get_me_sends_api_key_header() -> None:
    route = respx.get("https://g2b.test/v1/getMe").mock(
        return_value=httpx.Response(200, json={"user_id": 1, "username": "u", "balance": 12.3})
    )
    me = await _client().get_me()
    assert me["balance"] == 12.3
    assert route.called
    assert route.calls.last.request.headers["X-API-Key"] == "test-key"


@respx.mock
async def test_voucher_purchase_completed_returns_codes() -> None:
    respx.post("https://g2b.test/v1/products/42/purchase").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order_id": 100,
                "status": "COMPLETED",
                "delivery_items": ["A1", "A2"],
            },
        )
    )
    out = await _client().purchase_voucher(product_id="42", quantity=2, idempotency_key="task-abc")
    assert out.status == "completed"
    assert out.g2b_order_id == "100"
    assert out.delivery_items == ["A1", "A2"]


@respx.mock
async def test_voucher_purchase_pending_signals_polling_needed() -> None:
    route = respx.post("https://g2b.test/v1/products/42/purchase").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order_id": 101,
                "status": "PENDING",
                "delivery_items": None,
            },
        )
    )
    out = await _client().purchase_voucher(product_id="42", quantity=1, idempotency_key="task-x")
    assert out.status == "pending"
    assert out.delivery_items is None
    assert route.calls.last.request.headers["X-Idempotency-Key"] == "task-x"


@respx.mock
async def test_voucher_delivery_polling_states() -> None:
    # 202 → pending
    respx.get("https://g2b.test/v1/orders/101/delivery").mock(return_value=httpx.Response(202))
    out = await _client().poll_voucher_delivery("101")
    assert out.status == "pending"
    assert out.delivery_items is None

    respx.reset()
    # 200 → completed
    respx.get("https://g2b.test/v1/orders/101/delivery").mock(
        return_value=httpx.Response(200, json={"delivery_items": ["KEY"]})
    )
    out = await _client().poll_voucher_delivery("101")
    assert out.status == "completed"
    assert out.delivery_items == ["KEY"]

    respx.reset()
    # 410 → terminal failure
    respx.get("https://g2b.test/v1/orders/102/delivery").mock(
        return_value=httpx.Response(410, text="REFUNDED")
    )
    with pytest.raises(G2bTerminalFailure):
        await _client().poll_voucher_delivery("102")


@respx.mock
async def test_game_order_create_and_status() -> None:
    create = respx.post("https://g2b.test/v1/games/pubg_mobile/order").mock(
        return_value=httpx.Response(200, json={"order_id": 999, "status": "PENDING"})
    )
    created = await _client().create_game_order(
        game_code="pubg_mobile",
        catalogue_name="60 UC",
        player_id="5679523421",
        server_id=None,
        charname=None,
        callback_url="https://yupay.test/api/v1/webhooks/g2b/s",
        remark="yupay:abc",
        idempotency_key="task-game",
    )
    assert created.status == "pending"
    assert created.g2b_order_id == "999"
    sent = create.calls.last.request
    assert sent.headers["X-Idempotency-Key"] == "task-game"

    respx.post("https://g2b.test/v1/games/order/status").mock(
        return_value=httpx.Response(
            200,
            json={"order_id": 999, "status": "COMPLETED", "message": "done"},
        )
    )
    status = await _client().get_game_order_status(g2b_order_id="999", game_code="pubg_mobile")
    assert status.status == "completed"
    assert status.message == "done"


@respx.mock
async def test_429_retries_with_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("yupay.modules.fulfillment.suppliers.g2b_client.asyncio.sleep", _fake_sleep)
    # First two attempts 429, third 200.
    respx.get("https://g2b.test/v1/getMe").mock(
        side_effect=[
            httpx.Response(429, json={"detail": "slow down"}),
            httpx.Response(429, json={"detail": "slow down"}),
            httpx.Response(200, json={"username": "u", "balance": 1}),
        ]
    )
    me = await _client(max_retries=3).get_me()
    assert me["balance"] == 1
    # Exponential backoff: 1s, 2s.
    assert sleeps == [1.0, 2.0]


@respx.mock
async def test_401_does_not_retry() -> None:
    route = respx.get("https://g2b.test/v1/getMe").mock(
        return_value=httpx.Response(401, text="invalid key")
    )
    with pytest.raises(G2bError) as excinfo:
        await _client().get_me()
    assert excinfo.value.status == 401
    assert route.call_count == 1  # ONE call, no retries — critical for IP-ban safety.


@respx.mock
async def test_network_error_raises_upstream_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("yupay.modules.fulfillment.suppliers.g2b_client.asyncio.sleep", _fake_sleep)
    respx.get("https://g2b.test/v1/getMe").mock(side_effect=httpx.ConnectTimeout("timeout"))
    with pytest.raises(UpstreamUnavailableError):
        await _client(max_retries=1).get_me()


@respx.mock
async def test_check_player_200_valid() -> None:
    respx.post("https://g2b.test/v1/games/checkPlayerId").mock(
        return_value=httpx.Response(200, json={"valid": "valid", "name": "JAMA"})
    )
    out = await _client().games_check_player(
        game_code="pubgm", player_id="5395045830", server_id=None, charname=None
    )
    assert out["valid"] == "valid"
    assert out["name"] == "JAMA"


@respx.mock
async def test_check_player_400_invalid_verdict_is_unwrapped_not_raised() -> None:
    # G2B returns HTTP 400 for an invalid id, with the verdict in the body.
    # The client must return that body, NOT raise — so the caller can tell an
    # invalid id apart from a real error.
    respx.post("https://g2b.test/v1/games/checkPlayerId").mock(
        return_value=httpx.Response(400, json={"valid": "invalid", "name": ""})
    )
    out = await _client().games_check_player(
        game_code="pubgm", player_id="9", server_id=None, charname=None
    )
    assert out["valid"] == "invalid"


@respx.mock
async def test_check_player_400_without_verdict_raises() -> None:
    # A 400 that is NOT a verdict (no ``valid`` key) is a genuine error.
    respx.post("https://g2b.test/v1/games/checkPlayerId").mock(
        return_value=httpx.Response(400, json={"message": "bad request"})
    )
    with pytest.raises(G2bError) as excinfo:
        await _client().games_check_player(
            game_code="pubgm", player_id="9", server_id=None, charname=None
        )
    assert excinfo.value.status == 400
