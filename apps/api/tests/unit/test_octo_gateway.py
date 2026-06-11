"""OctoClient / OctoGateway error paths: HTTP failures, malformed responses,
intent and refund guards. No network — httpx.MockTransport and fake clients.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from yupay.core import config as cfg
from yupay.modules.payments.gateways.base import PaymentGatewayError
from yupay.modules.payments.gateways.octo import (
    OctoClient,
    OctoGateway,
    OctoRefundResult,
)

pytestmark = pytest.mark.asyncio


def _client(handler) -> OctoClient:
    transport = httpx.MockTransport(handler)
    return OctoClient(
        shop_id="123",
        secret="sec",
        base_url="https://octo.test",
        max_retries=1,
        client=httpx.AsyncClient(transport=transport),
    )


@pytest.fixture
def _octo_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OCTO_SHOP_ID", "123")
    monkeypatch.setenv("OCTO_SECRET", "sec")
    monkeypatch.setenv("OCTO_SIGNATURE_KEY", "unique-key")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


# ---------- client ----------


async def test_client_4xx_raises() -> None:
    c = _client(lambda req: httpx.Response(400, text="bad request"))
    with pytest.raises(PaymentGatewayError, match="HTTP 400"):
        await c.refund(octo_payment_uuid="u", shop_refund_id="r", amount=Decimal("1.00"))


async def test_client_5xx_exhausts_retries() -> None:
    calls = {"n": 0}

    def handler(req: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502, text="bad gateway")

    c = _client(handler)
    with pytest.raises(PaymentGatewayError, match="upstream error"):
        await c.refund(octo_payment_uuid="u", shop_refund_id="r", amount=Decimal("1.00"))
    assert calls["n"] == 2  # initial + 1 retry


async def test_client_network_error_exhausts_retries() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=req)

    c = _client(handler)
    with pytest.raises(PaymentGatewayError, match="network error"):
        await c.refund(octo_payment_uuid="u", shop_refund_id="r", amount=Decimal("1.00"))


async def test_client_non_json_raises() -> None:
    c = _client(lambda req: httpx.Response(200, text="<html>nope</html>"))
    with pytest.raises(PaymentGatewayError, match="non-JSON"):
        await c.refund(octo_payment_uuid="u", shop_refund_id="r", amount=Decimal("1.00"))


async def test_client_api_error_code_raises() -> None:
    c = _client(lambda req: httpx.Response(200, json={"error": 13, "errMessage": "no shop"}))
    with pytest.raises(PaymentGatewayError, match="octo error 13"):
        await c.refund(octo_payment_uuid="u", shop_refund_id="r", amount=Decimal("1.00"))


async def test_prepare_payment_missing_fields_raises() -> None:
    c = _client(lambda req: httpx.Response(200, json={"error": 0, "data": {}}))
    with pytest.raises(PaymentGatewayError, match="octo_pay_url"):
        await c.prepare_payment(
            shop_transaction_id="t",
            total_sum=Decimal("10.00"),
            currency="UZS",
            description="d",
            return_url="https://r",
            notify_url="https://n",
            init_time="2026-06-11 00:00:00",
        )


async def test_refund_missing_refund_id_raises() -> None:
    c = _client(lambda req: httpx.Response(200, json={"error": 0, "data": {"status": "ok"}}))
    with pytest.raises(PaymentGatewayError, match="refund_id"):
        await c.refund(octo_payment_uuid="u", shop_refund_id="r", amount=Decimal("1.00"))


# ---------- gateway guards ----------


async def test_create_intent_rejects_unsupported_currency(_octo_env: None) -> None:
    gw = OctoGateway()
    order = SimpleNamespace(id="o1", currency="EUR", total_charged=Decimal("10"))
    with pytest.raises(PaymentGatewayError, match="does not support currency"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_create_intent_rejects_non_positive_amount(_octo_env: None) -> None:
    gw = OctoGateway()
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("0"))
    with pytest.raises(PaymentGatewayError, match="non-positive"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_verify_webhook_shape_guards(_octo_env: None) -> None:
    gw = OctoGateway()
    with pytest.raises(PaymentGatewayError, match="invalid body"):
        await gw.verify_webhook(headers={}, body=b"\xff\xfe not json")
    with pytest.raises(PaymentGatewayError, match="not a JSON object"):
        await gw.verify_webhook(headers={}, body=b'["list"]')
    with pytest.raises(PaymentGatewayError, match="missing octo_payment_UUID"):
        await gw.verify_webhook(headers={}, body=b'{"signature": "x"}')


async def test_refund_guards(_octo_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    gw = OctoGateway()
    payment = SimpleNamespace(id="p1", external_id="uuid-1")
    with pytest.raises(PaymentGatewayError, match="positive"):
        await gw.refund(payment=payment, amount=Decimal("0"))
    with pytest.raises(PaymentGatewayError, match="no octo_payment_UUID"):
        await gw.refund(payment=SimpleNamespace(id="p2", external_id=None), amount=Decimal("1"))

    # Empty strings (not delenv): process env outranks any local .env file
    # pydantic-settings might pick up when the suite runs from the repo root.
    monkeypatch.setenv("OCTO_SHOP_ID", "")
    monkeypatch.setenv("OCTO_SECRET", "")
    cfg.get_settings.cache_clear()
    with pytest.raises(PaymentGatewayError, match="not configured"):
        await gw.refund(payment=payment, amount=Decimal("1"))


async def test_refund_happy_path_via_injected_client(_octo_env: None) -> None:
    class _FakeClient(OctoClient):
        def __init__(self) -> None:
            super().__init__(shop_id="123", secret="sec", base_url="https://octo.test")

        async def refund(self, **_kw: Any) -> OctoRefundResult:  # type: ignore[override]
            return OctoRefundResult(refund_id="rf-1", status="succeeded")

    gw = OctoGateway(client=_FakeClient())
    result = await gw.refund(
        payment=SimpleNamespace(id="p1", external_id="uuid-1"), amount=Decimal("5.00")
    )
    assert result.external_refund_id == "rf-1"
    assert result.amount == Decimal("5.00")
