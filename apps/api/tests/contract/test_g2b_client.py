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

import json
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
    # The real G2B API wraps the order object under an ``order`` key (and adds
    # a top-level ``success``). The ``order_id`` / ``status`` fields live INSIDE
    # that wrapper — reading them off the top level yields ``None`` and silently
    # persists ``external_order_id="None"``, which is exactly what stranded a
    # completed prod top-up in ``in_progress`` (the flat webhook could never
    # match the mis-stored id). Captured live from api.g2bulk.com.
    create = respx.post("https://g2b.test/v1/games/pubg_mobile/order").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order": {"order_id": 999, "status": "PENDING", "message": "Create success"},
            },
        )
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

    status_route = respx.post("https://g2b.test/v1/games/order/status").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order": {"order_id": 999, "status": "COMPLETED", "message": "done"},
            },
        )
    )
    # external_order_id round-trips as a string ("999") but G2B rejects a string
    # order_id in the status body with HTTP 400 "Failed to parse request body" —
    # it must be a JSON number. Assert we send it numeric.
    status = await _client().get_game_order_status(g2b_order_id="999", game_code="pubg_mobile")
    sent_body = json.loads(status_route.calls.last.request.content)
    assert sent_body["order_id"] == 999
    assert isinstance(sent_body["order_id"], int)
    assert status.g2b_order_id == "999"
    assert status.status == "completed"
    assert status.message == "done"


@respx.mock
async def test_game_order_flat_response_still_parsed() -> None:
    """Back-compat: a flat (un-wrapped) response must keep working.

    We defensively unwrap ``order`` only when present, so any endpoint/version
    that returns fields at the top level (like ``getMe`` does today) is
    unaffected.
    """
    respx.post("https://g2b.test/v1/games/pubg_mobile/order").mock(
        return_value=httpx.Response(200, json={"order_id": 777, "status": "PROCESSING"})
    )
    created = await _client().create_game_order(
        game_code="pubg_mobile",
        catalogue_name="60 UC",
        player_id="5679523421",
        server_id=None,
        charname=None,
        callback_url=None,
        remark=None,
        idempotency_key="task-flat",
    )
    assert created.g2b_order_id == "777"
    assert created.status == "processing"


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


@respx.mock
async def test_fetch_product_reads_stock() -> None:
    """The stock sweep's read path. Flat object, as G2B actually answers."""
    respx.get("https://g2b.test/v1/products/107").mock(
        return_value=httpx.Response(
            200,
            json={"id": 107, "title": "800 Robux Global", "unit_price": 9, "stock": 422},
        )
    )
    got = await _client().fetch_product("107")
    assert got is not None
    assert got["stock"] == 422
    assert got["unit_price"] == 9


@respx.mock
async def test_fetch_product_unwraps_a_wrapped_body() -> None:
    """Tolerated for the same reason ``fetch_products`` tolerates it: the list
    endpoint wraps its rows, and nothing documents that the detail one will not."""
    respx.get("https://g2b.test/v1/products/93").mock(
        return_value=httpx.Response(200, json={"product": {"id": 93, "stock": 3}})
    )
    got = await _client().fetch_product("93")
    assert got == {"id": 93, "stock": 3}


@respx.mock
async def test_fetch_product_404_is_not_an_error() -> None:
    """A withdrawn product is an answer, not a fault — the caller turns None
    into "no stock" rather than alerting on it."""
    respx.get("https://g2b.test/v1/products/99999999").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )
    assert await _client().fetch_product("99999999") is None


@respx.mock
async def test_fetch_product_other_errors_still_raise() -> None:
    """Only 404 is swallowed. A 500 must not read as "the product is gone",
    or one bad afternoon at the supplier would empty the shelf — it propagates
    as the transport failure it is, and the sweep counts it as an error."""
    respx.get("https://g2b.test/v1/products/107").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(UpstreamUnavailableError):
        await _client(max_retries=0).fetch_product("107")
