"""UzumGateway: availability, checkout-URL construction, and the locked refusals.

Uzum's checkout is a plain query-string GET URL (``open-service``), not an API
call — no HTTP client to fake here. Mirrors ``test_payme_gateway.py`` for the
settings-cache convention; env var names mirror ``test_uzum_config.py`` /
``test_uzum_webhook.py``.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlencode

import pytest

# Calling UzumGateway.create_intent lazily imports uzum.service (→
# payments.service → payments.gateways → this module), same reasoning as
# tests/unit/test_payme_gateway.py; loading the router package first resolves
# it the same way ``bootstrap.create_app`` does.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core import config as cfg
from yupay.modules.payments.gateways import REGISTRY
from yupay.modules.payments.gateways.base import PaymentGatewayError, PaymentNotIntegratedError
from yupay.modules.payments.gateways.uzum import UzumGateway

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _uzum_env(monkeypatch: pytest.MonkeyPatch):
    """Configure Uzum (service id + sandbox creds) and clear the settings cache.

    Cleared on both sides: ``get_settings`` is process-lifetime cached via
    ``lru_cache``, so leaving it dirty would freeze the result for whichever
    test runs next, in this module or any other.
    """
    monkeypatch.setenv("UZUM_SERVICE_ID", "101202")
    monkeypatch.setenv("UZUM_TEST_LOGIN", "uzum-sandbox")
    monkeypatch.setenv("UZUM_TEST_PASSWORD", "sandbox-secret")
    monkeypatch.setenv("UZUM_LOGIN", "")
    monkeypatch.setenv("UZUM_PASSWORD", "")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def test_available_false_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UZUM_SERVICE_ID", "")
    monkeypatch.setenv("UZUM_LOGIN", "")
    monkeypatch.setenv("UZUM_PASSWORD", "")
    monkeypatch.setenv("UZUM_TEST_LOGIN", "")
    monkeypatch.setenv("UZUM_TEST_PASSWORD", "")
    cfg.get_settings.cache_clear()
    try:
        assert UzumGateway().available is False
    finally:
        cfg.get_settings.cache_clear()


def test_available_true_with_service_id_and_test_creds(_uzum_env: None) -> None:
    assert UzumGateway().available is True


def test_available_true_with_prod_creds(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers the OR-branch of ``available`` left untested by ``_uzum_env``:
    real (production/cabinet) credentials alone, with the sandbox test creds
    blank, are also sufficient to be considered available."""
    monkeypatch.setenv("UZUM_SERVICE_ID", "101202")
    monkeypatch.setenv("UZUM_LOGIN", "uzum-prod")
    monkeypatch.setenv("UZUM_PASSWORD", "prod-secret")
    monkeypatch.setenv("UZUM_TEST_LOGIN", "")
    monkeypatch.setenv("UZUM_TEST_PASSWORD", "")
    cfg.get_settings.cache_clear()
    try:
        assert UzumGateway().available is True
    finally:
        cfg.get_settings.cache_clear()


async def test_create_intent_builds_exact_checkout_url(_uzum_env: None) -> None:
    gw = UzumGateway()
    order = SimpleNamespace(id="order-123", currency="UZS", total_charged=Decimal("130000.00"))
    intent = await gw.create_intent(
        db=cast(Any, None), order=order, return_url="https://return.example"
    )

    expected_query = urlencode(
        {
            "serviceId": 101202,
            "orderId": "order-123",
            "redirectUrl": "https://return.example",
        }
    )
    assert intent.intent_url == f"https://uzumbank.uz/open-service?{expected_query}"
    assert intent.external_id == "uzum:order-123"
    assert intent.status == "pending"
    assert intent.extra_metadata == {"amount_tiyin": 13_000_000}


async def test_create_intent_rejects_non_uzs(_uzum_env: None) -> None:
    gw = UzumGateway()
    order = SimpleNamespace(id="o1", currency="USD", total_charged=Decimal("10"))
    with pytest.raises(PaymentGatewayError, match="UZS"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_create_intent_rejects_non_positive_amount(_uzum_env: None) -> None:
    gw = UzumGateway()
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("0"))
    with pytest.raises(PaymentGatewayError, match="non-positive"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_create_intent_rejects_non_integral_tiyin(_uzum_env: None) -> None:
    gw = UzumGateway()
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("10.005"))
    with pytest.raises(PaymentGatewayError, match="exact tiyin"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_verify_webhook_not_integrated(_uzum_env: None) -> None:
    with pytest.raises(PaymentNotIntegratedError, match="payments/uzum"):
        await UzumGateway().verify_webhook(headers={}, body=b"{}")


async def test_refund_refuses(_uzum_env: None) -> None:
    with pytest.raises(PaymentGatewayError, match="reverse"):
        await UzumGateway().refund(payment=cast(Any, None), amount=Decimal("1"))


def test_registry_has_uzum_gateway() -> None:
    assert isinstance(REGISTRY["uzum"], UzumGateway)
    assert REGISTRY["uzum"].provider == "uzum"
