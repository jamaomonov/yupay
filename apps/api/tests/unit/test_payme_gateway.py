"""PaymeGateway: availability, checkout-URL construction, and the locked refusals.

Payme's checkout is a base64-encoded GET URL, not an API call — no HTTP client to
fake here (mirrors ``test_octo_gateway.py`` / ``test_payme_config.py`` for the
settings-cache convention).
"""

from __future__ import annotations

import base64
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest

# Calling PaymeGateway.create_intent lazily imports payme.service (→
# payments.service → wallet.api → api.v1 → payme.api), same as
# tests/integration/test_payme_service.py; loading the router package first
# resolves it the same way ``bootstrap.create_app`` does.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core import config as cfg
from yupay.modules.payments.gateways import REGISTRY
from yupay.modules.payments.gateways.base import PaymentGatewayError, PaymentNotIntegratedError
from yupay.modules.payments.gateways.payme import PaymeGateway

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _payme_env(monkeypatch: pytest.MonkeyPatch):
    """Configure Payme (merchant id + sandbox key) and clear the settings cache.

    Cleared on both sides: ``get_settings`` is process-lifetime cached via
    ``lru_cache``, so leaving it dirty would freeze the result for whichever
    test runs next, in this module or any other.
    """
    monkeypatch.setenv("PAYME_MERCHANT_ID", "merchant-1")
    monkeypatch.setenv("PAYME_TEST_KEY", "test-key-1")
    monkeypatch.setenv("PAYME_KEY", "")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def test_available_false_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYME_MERCHANT_ID", "")
    monkeypatch.setenv("PAYME_KEY", "")
    monkeypatch.setenv("PAYME_TEST_KEY", "")
    cfg.get_settings.cache_clear()
    try:
        assert PaymeGateway().available is False
    finally:
        cfg.get_settings.cache_clear()


def test_available_true_with_merchant_and_test_key(_payme_env: None) -> None:
    assert PaymeGateway().available is True


async def test_create_intent_builds_exact_checkout_url(_payme_env: None) -> None:
    gw = PaymeGateway()
    order = SimpleNamespace(id="order-123", currency="UZS", total_charged=Decimal("15000"))
    intent = await gw.create_intent(
        db=cast(Any, None), order=order, return_url="https://return.example"
    )

    expected_params = "m=merchant-1;ac.order_id=order-123;a=1500000;c=https://return.example;l=ru"
    expected_b64 = base64.b64encode(expected_params.encode()).decode()
    assert intent.intent_url == f"https://checkout.paycom.uz/{expected_b64}"
    assert intent.external_id == "payme:order-123"
    assert intent.status == "pending"
    assert intent.extra_metadata == {"amount_tiyin": 1500000}


async def test_create_intent_rejects_non_uzs(_payme_env: None) -> None:
    gw = PaymeGateway()
    order = SimpleNamespace(id="o1", currency="USD", total_charged=Decimal("10"))
    with pytest.raises(PaymentGatewayError, match="UZS"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_create_intent_rejects_non_positive_amount(_payme_env: None) -> None:
    gw = PaymeGateway()
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("0"))
    with pytest.raises(PaymentGatewayError, match="non-positive"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_create_intent_rejects_non_integral_tiyin(_payme_env: None) -> None:
    gw = PaymeGateway()
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("10.005"))
    with pytest.raises(PaymentGatewayError, match="exact tiyin"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_verify_webhook_not_integrated(_payme_env: None) -> None:
    with pytest.raises(PaymentNotIntegratedError, match="merchant JSON-RPC"):
        await PaymeGateway().verify_webhook(headers={}, body=b"{}")


async def test_refund_refuses(_payme_env: None) -> None:
    with pytest.raises(PaymentGatewayError, match="Payme cabinet"):
        await PaymeGateway().refund(payment=cast(Any, None), amount=Decimal("1"))


def test_registry_has_payme_gateway() -> None:
    assert isinstance(REGISTRY["payme"], PaymeGateway)
    assert REGISTRY["payme"].provider == "payme"
