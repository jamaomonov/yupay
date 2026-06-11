"""Unit tests for InpayGateway pure logic: status mapping, currency / min-amount
guards, refund refusal, and bearer-token caching. No DB; HTTP via an injected
fake client.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

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
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


@pytest.mark.asyncio
async def test_create_intent_rejects_below_minimum(_inpay_env: None) -> None:
    gw = InpayGateway(client=_FakeClient())
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("500"))
    with pytest.raises(PaymentGatewayError, match="minimum"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


@pytest.mark.asyncio
async def test_create_intent_happy(_inpay_env: None) -> None:
    gw = InpayGateway(client=_FakeClient())
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("15000"))
    intent = await gw.create_intent(db=cast(Any, None), order=order, return_url="")
    assert intent.external_id == "oid-1"
    assert intent.intent_url == "https://inpay/checkout/oid-1"
    assert intent.status == "pending"


@pytest.mark.asyncio
async def test_bearer_token_is_cached(_inpay_env: None) -> None:
    fake = _FakeClient()
    gw = InpayGateway(client=fake)
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("15000"))
    await gw.create_intent(db=cast(Any, None), order=order, return_url="")
    await gw.create_intent(db=cast(Any, None), order=order, return_url="")
    assert fake.authorize_calls == 1  # second call reuses the cached token


@pytest.mark.asyncio
async def test_concurrent_intents_authorize_once(_inpay_env: None) -> None:
    """Two concurrent requests on a cold token cache must not both hit
    ``/authorization`` — the singleton gateway serialises the refresh."""
    import asyncio

    class _SlowAuthClient(_FakeClient):
        async def authorize(self) -> str:  # type: ignore[override]
            self.authorize_calls += 1
            await asyncio.sleep(0.01)  # widen the race window
            return "BEARER"

    fake = _SlowAuthClient()
    gw = InpayGateway(client=fake)
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("15000"))
    await asyncio.gather(
        gw.create_intent(db=cast(Any, None), order=order, return_url=""),
        gw.create_intent(db=cast(Any, None), order=order, return_url=""),
    )
    assert fake.authorize_calls == 1


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


# ---------- client error paths (httpx.MockTransport, no network) ----------


def _http_client(handler) -> InpayClient:
    import httpx

    return InpayClient(
        merchant_id="22715",
        merchant_token="tok-32",
        base_url="https://inpay.test/api/v1",
        max_retries=1,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.mark.asyncio
async def test_client_4xx_raises() -> None:
    import httpx

    c = _http_client(lambda req: httpx.Response(403, text="forbidden"))
    with pytest.raises(PaymentGatewayError, match="HTTP 403"):
        await c.authorize()


@pytest.mark.asyncio
async def test_client_5xx_exhausts_retries() -> None:
    import httpx

    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, text="down")

    c = _http_client(handler)
    with pytest.raises(PaymentGatewayError, match="upstream error"):
        await c.authorize()
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_client_non_json_raises() -> None:
    import httpx

    c = _http_client(lambda req: httpx.Response(200, text="<html>"))
    with pytest.raises(PaymentGatewayError, match="non-JSON"):
        await c.authorize()


@pytest.mark.asyncio
async def test_client_success_false_raises() -> None:
    import httpx

    c = _http_client(
        lambda req: httpx.Response(200, json={"success": False, "message": "bad merchant"})
    )
    with pytest.raises(PaymentGatewayError, match="bad merchant"):
        await c.authorize()


@pytest.mark.asyncio
async def test_authorize_missing_token_raises() -> None:
    import httpx

    c = _http_client(lambda req: httpx.Response(200, json={"success": True}))
    with pytest.raises(PaymentGatewayError, match="bearer_token"):
        await c.authorize()


@pytest.mark.asyncio
async def test_create_missing_fields_raises() -> None:
    import httpx

    c = _http_client(lambda req: httpx.Response(200, json={"order_id": "o-1"}))
    with pytest.raises(PaymentGatewayError, match="order_id / pay_url"):
        await c.create(
            bearer="B", amount=Decimal("5000.00"), description="d", callback_url="https://cb"
        )


@pytest.mark.asyncio
async def test_get_status_missing_status_raises() -> None:
    import httpx

    c = _http_client(lambda req: httpx.Response(200, json={"order_id": "o-1"}))
    with pytest.raises(PaymentGatewayError, match="missing status"):
        await c.get_status(bearer="B", order_id="o-1")


# ---------- remaining gateway guards ----------


@pytest.mark.asyncio
async def test_create_intent_missing_amount(_inpay_env: None) -> None:
    gw = InpayGateway(client=_FakeClient())
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=None)
    with pytest.raises(PaymentGatewayError, match="missing"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


@pytest.mark.asyncio
async def test_verify_webhook_shape_guards(_inpay_env: None) -> None:
    gw = InpayGateway(client=_FakeClient())
    with pytest.raises(PaymentGatewayError, match="invalid body"):
        await gw.verify_webhook(headers={}, body=b"\xff\xfe nope")
    with pytest.raises(PaymentGatewayError, match="not a JSON object"):
        await gw.verify_webhook(headers={}, body=b"[1, 2]")
    with pytest.raises(PaymentGatewayError, match="missing order_id"):
        await gw.verify_webhook(headers={}, body=b"{}")


@pytest.mark.asyncio
async def test_verify_webhook_requires_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Empty strings (not delenv): process env outranks any local .env file
    # pydantic-settings might pick up when the suite runs from the repo root.
    monkeypatch.setenv("INPAY_MERCHANT_ID", "")
    monkeypatch.setenv("INPAY_MERCHANT_TOKEN", "")
    cfg.get_settings.cache_clear()
    try:
        gw = InpayGateway()
        with pytest.raises(PaymentGatewayError, match="not configured"):
            await gw.verify_webhook(headers={}, body=b'{"order_id": "o-1"}')
    finally:
        cfg.get_settings.cache_clear()
