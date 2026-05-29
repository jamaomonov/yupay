"""Contract tests for :class:`OctoClient` using respx as the HTTP transport.

Verifies the wire format only (no DB): credentials land in the body, a
successful ``prepare_payment`` / ``refund`` is parsed, ``error != 0`` raises a
``PaymentGatewayError`` carrying ``errMessage``, and network / 5xx are retried
then surfaced as a gateway error.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx
import pytest
import respx
from yupay.modules.payments.gateways.base import PaymentGatewayError
from yupay.modules.payments.gateways.octo import OctoClient

pytestmark = pytest.mark.asyncio

BASE = "https://octo.test"


def _client(**kwargs: Any) -> OctoClient:
    defaults: dict[str, Any] = {
        "shop_id": "123",
        "secret": "shop-secret",
        "base_url": BASE,
        "timeout_seconds": 2.0,
        "max_retries": 2,
    }
    defaults.update(kwargs)
    return OctoClient(**defaults)


@respx.mock
async def test_prepare_payment_success_sends_credentials() -> None:
    route = respx.post(f"{BASE}/prepare_payment").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": 0,
                "data": {
                    "octo_payment_UUID": "uuid-1",
                    "octo_pay_url": "https://pay.octo.test/uuid-1",
                    "status": "created",
                },
            },
        )
    )
    result = await _client().prepare_payment(
        shop_transaction_id="tx-1",
        total_sum=Decimal("1000.00"),
        currency="UZS",
        description="order",
        return_url="https://app/return",
        notify_url="https://app/notify",
        init_time="2026-05-29 10:00:00",
    )
    assert result.octo_payment_uuid == "uuid-1"
    assert result.pay_url == "https://pay.octo.test/uuid-1"
    assert route.called
    sent = route.calls.last.request
    body = sent.read().decode()
    assert '"octo_shop_id":123' in body or '"octo_shop_id": 123' in body
    assert "shop-secret" in body
    assert "tx-1" in body
    assert '"auto_capture":true' in body or '"auto_capture": true' in body


@respx.mock
async def test_prepare_payment_error_raises_with_message() -> None:
    respx.post(f"{BASE}/prepare_payment").mock(
        return_value=httpx.Response(200, json={"error": 2, "errMessage": "Wrong secret"})
    )
    with pytest.raises(PaymentGatewayError, match="Wrong secret"):
        await _client().prepare_payment(
            shop_transaction_id="tx-2",
            total_sum=Decimal("10"),
            currency="UZS",
            description="x",
            return_url="r",
            notify_url="n",
            init_time="2026-05-29 10:00:00",
        )


@respx.mock
async def test_refund_success() -> None:
    respx.post(f"{BASE}/refund").mock(
        return_value=httpx.Response(
            200,
            json={
                "error": 0,
                "data": {"refund_id": "ref-1", "status": "succeeded"},
            },
        )
    )
    result = await _client().refund(
        octo_payment_uuid="uuid-1", shop_refund_id="rf-1", amount=Decimal("500.00")
    )
    assert result.refund_id == "ref-1"
    assert result.status == "succeeded"


@respx.mock
async def test_refund_error_raises() -> None:
    respx.post(f"{BASE}/refund").mock(
        return_value=httpx.Response(200, json={"error": 5, "errMessage": "amount too large"})
    )
    with pytest.raises(PaymentGatewayError, match="amount too large"):
        await _client().refund(
            octo_payment_uuid="uuid-1", shop_refund_id="rf-2", amount=Decimal("999999999")
        )


@respx.mock
async def test_network_error_exhausts_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    respx.post(f"{BASE}/prepare_payment").mock(side_effect=httpx.ConnectError("boom"))
    with pytest.raises(PaymentGatewayError, match="network"):
        await _client(max_retries=1).prepare_payment(
            shop_transaction_id="tx-3",
            total_sum=Decimal("10"),
            currency="UZS",
            description="x",
            return_url="r",
            notify_url="n",
            init_time="2026-05-29 10:00:00",
        )


@respx.mock
async def test_5xx_is_retried_then_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    route = respx.post(f"{BASE}/prepare_payment").mock(return_value=httpx.Response(503))
    with pytest.raises(PaymentGatewayError, match="upstream error"):
        await _client(max_retries=2).prepare_payment(
            shop_transaction_id="tx-4",
            total_sum=Decimal("10"),
            currency="UZS",
            description="x",
            return_url="r",
            notify_url="n",
            init_time="2026-05-29 10:00:00",
        )
    assert route.call_count == 3  # initial + 2 retries
