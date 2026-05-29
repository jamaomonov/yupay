"""Contract tests for :class:`InpayClient` using respx as the HTTP transport.

Verifies the wire format only (no DB): authorization returns a bearer token,
create sends credentials + Bearer header and parses order_id/pay_url, status
reads the transaction status, and ``success: false`` / network / 5xx surface as
``PaymentGatewayError``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from yupay.modules.payments.gateways.base import PaymentGatewayError
from yupay.modules.payments.gateways.inpay import InpayClient

pytestmark = pytest.mark.asyncio

BASE = "https://inpay.test/api/v1"


def _client(**kwargs: Any) -> InpayClient:
    defaults: dict[str, Any] = {
        "merchant_id": "22715",
        "merchant_token": "tok-32",
        "base_url": BASE,
        "timeout_seconds": 2.0,
        "max_retries": 2,
    }
    defaults.update(kwargs)
    return InpayClient(**defaults)


@respx.mock
async def test_authorize_returns_bearer_and_sends_credentials() -> None:
    route = respx.get(f"{BASE}/authorization/").mock(
        return_value=httpx.Response(200, json={"success": True, "bearer_token": "BEARER-1"})
    )
    token = await _client().authorize()
    assert token == "BEARER-1"
    assert route.called
    req = route.calls.last.request
    assert "merchant_id=22715" in str(req.url)
    assert "merchant_token=tok-32" in str(req.url)


@respx.mock
async def test_create_sends_bearer_and_body() -> None:
    route = respx.post(f"{BASE}/create/").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "order_id": "abc123",
                "pay_url": "https://inpay.test/checkout/abc123",
            },
        )
    )
    result = await _client().create(
        bearer="BEARER-1",
        amount=Decimal("15000"),
        description="order",
        callback_url="https://app/cb",
    )
    assert result.order_id == "abc123"
    assert result.pay_url == "https://inpay.test/checkout/abc123"
    req = route.calls.last.request
    assert req.headers["Authorization"] == "Bearer BEARER-1"
    body = req.read().decode()
    assert "22715" in body
    assert "tok-32" in body
    assert "15000" in body


@respx.mock
async def test_get_status_reads_status() -> None:
    respx.get(f"{BASE}/transactions/").mock(
        return_value=httpx.Response(
            200, json={"success": True, "order_id": "abc123", "status": "success"}
        )
    )
    status = await _client().get_status(bearer="BEARER-1", order_id="abc123")
    assert status == "success"


@respx.mock
async def test_create_failure_raises() -> None:
    respx.post(f"{BASE}/create/").mock(
        return_value=httpx.Response(200, json={"success": False, "message": "amount too small"})
    )
    with pytest.raises(PaymentGatewayError, match="amount too small"):
        await _client().create(
            bearer="B", amount=Decimal("100"), description="x", callback_url="c"
        )


@respx.mock
async def test_authorize_missing_token_raises() -> None:
    respx.get(f"{BASE}/authorization/").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    with pytest.raises(PaymentGatewayError, match="missing bearer_token"):
        await _client().authorize()


@respx.mock
async def test_network_error_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    respx.get(f"{BASE}/authorization/").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(PaymentGatewayError, match="network"):
        await _client(max_retries=1).authorize()
