"""Unit tests for InpayGateway pure logic: status mapping, currency / min-amount
guards, refund refusal, and bearer-token caching. No DB; HTTP via an injected
fake client.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from yupay.core import config as cfg
from yupay.modules.payments.gateways.base import PaymentGatewayError
from yupay.modules.payments.gateways.inpay import (
    InpayClient,
    InpayCreateResult,
    InpayGateway,
    _map_status,
)


def test_map_status() -> None:
    assert _map_status("success") == "succeeded"
    assert _map_status("failed") == "failed"
    assert _map_status("cancelled") == "cancelled"
    assert _map_status("pending") == "pending"
    assert _map_status("whatever") == "pending"


@pytest.fixture
def _inpay_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INPAY_MERCHANT_ID", "22715")
    monkeypatch.setenv("INPAY_MERCHANT_TOKEN", "tok-32")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


class _FakeClient(InpayClient):
    """InpayClient with the network calls stubbed; counts authorize() calls."""

    def __init__(self) -> None:
        super().__init__(merchant_id="22715", merchant_token="tok-32", base_url="https://x")
        self.authorize_calls = 0

    async def authorize(self) -> str:  # type: ignore[override]
        self.authorize_calls += 1
        return "BEARER"

    async def create(self, **_kwargs: Any) -> InpayCreateResult:  # type: ignore[override]
        return InpayCreateResult(order_id="oid-1", pay_url="https://inpay/checkout/oid-1")

    async def get_status(self, **_kwargs: Any) -> str:  # type: ignore[override]
        return "success"


@pytest.mark.asyncio
async def test_create_intent_rejects_non_uzs(_inpay_env: None) -> None:
    gw = InpayGateway(client=_FakeClient())
    order = SimpleNamespace(id="o1", currency="USD", total_charged=Decimal("10000"))
    with pytest.raises(PaymentGatewayError, match="UZS"):
        await gw.create_intent(db=None, order=order, return_url="")


@pytest.mark.asyncio
async def test_create_intent_rejects_below_minimum(_inpay_env: None) -> None:
    gw = InpayGateway(client=_FakeClient())
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("500"))
    with pytest.raises(PaymentGatewayError, match="minimum"):
        await gw.create_intent(db=None, order=order, return_url="")


@pytest.mark.asyncio
async def test_create_intent_happy(_inpay_env: None) -> None:
    gw = InpayGateway(client=_FakeClient())
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("15000"))
    intent = await gw.create_intent(db=None, order=order, return_url="")
    assert intent.external_id == "oid-1"
    assert intent.intent_url == "https://inpay/checkout/oid-1"
    assert intent.status == "pending"


@pytest.mark.asyncio
async def test_bearer_token_is_cached(_inpay_env: None) -> None:
    fake = _FakeClient()
    gw = InpayGateway(client=fake)
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("15000"))
    await gw.create_intent(db=None, order=order, return_url="")
    await gw.create_intent(db=None, order=order, return_url="")
    assert fake.authorize_calls == 1  # second call reuses the cached token


@pytest.mark.asyncio
async def test_verify_webhook_reverifies_status(_inpay_env: None) -> None:
    gw = InpayGateway(client=_FakeClient())
    # Body claims "failed" but /transactions says "success" — we trust the API.
    import json

    body = json.dumps({"order_id": "oid-1", "status": "failed"}).encode()
    event = await gw.verify_webhook(headers={}, body=body)
    assert event.outcome == "succeeded"
    assert event.external_payment_id == "oid-1"
    assert event.external_event_id == "oid-1:success"


@pytest.mark.asyncio
async def test_refund_not_supported(_inpay_env: None) -> None:
    gw = InpayGateway(client=_FakeClient())
    payment = SimpleNamespace(id="p1", external_id="oid-1")
    with pytest.raises(PaymentGatewayError, match="no refund API"):
        await gw.refund(payment=payment, amount=Decimal("100"))
