"""ClickGateway: availability (per surface), checkout-URL construction, and locked refusals.

Click needs TWO gateway instances, not one — the web storefront and the
Telegram mini app each route through their own Click ``service_id`` +
``SECRET_KEY`` (see :mod:`yupay.modules.click.service`'s
``build_checkout_url`` and the ``ClickGateway`` module docstring). Mirrors
``test_uzum_gateway.py`` for the settings-cache convention; env var names
mirror ``test_click_signature.py``.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast
from urllib.parse import urlencode

import pytest

# Calling ClickGateway.create_intent lazily imports click.service (→
# payments.service → payments.gateways → this module), same reasoning as
# tests/unit/test_uzum_gateway.py; loading the router package first resolves
# it the same way ``bootstrap.create_app`` does.
import yupay.api.v1  # noqa: F401  isort: skip
from yupay.core import config as cfg
from yupay.modules.payments.gateways import REGISTRY
from yupay.modules.payments.gateways.base import PaymentGatewayError, PaymentNotIntegratedError
from yupay.modules.payments.gateways.click import ClickGateway

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _click_env(monkeypatch: pytest.MonkeyPatch):
    """Configure both Click surfaces (web + bot) and clear the settings cache.

    Cleared on both sides: ``get_settings`` is process-lifetime cached via
    ``lru_cache``, so leaving it dirty would freeze the result for whichever
    test runs next, in this module or any other.
    """
    monkeypatch.setenv("CLICK_MERCHANT_ID", "5000")
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", "108149")
    monkeypatch.setenv("CLICK_SERVICE_ID_BOT", "108150")
    monkeypatch.setenv("CLICK_SECRET_KEY_WEB", "web-secret-abc")
    monkeypatch.setenv("CLICK_SECRET_KEY_BOT", "bot-secret-xyz")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


def _blank_click_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLICK_MERCHANT_ID", "")
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", "")
    monkeypatch.setenv("CLICK_SERVICE_ID_BOT", "")
    monkeypatch.setenv("CLICK_SECRET_KEY_WEB", "")
    monkeypatch.setenv("CLICK_SECRET_KEY_BOT", "")


def test_available_false_when_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    _blank_click_env(monkeypatch)
    cfg.get_settings.cache_clear()
    try:
        assert ClickGateway(provider="click").available is False
        assert ClickGateway(provider="click_miniapp").available is False
    finally:
        cfg.get_settings.cache_clear()


def test_web_available_true_with_web_creds_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers the WEB-only branch of ``available`` — bot creds stay blank."""
    _blank_click_env(monkeypatch)
    monkeypatch.setenv("CLICK_MERCHANT_ID", "5000")
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", "108149")
    monkeypatch.setenv("CLICK_SECRET_KEY_WEB", "web-secret-abc")
    cfg.get_settings.cache_clear()
    try:
        assert ClickGateway(provider="click").available is True
        assert ClickGateway(provider="click_miniapp").available is False
    finally:
        cfg.get_settings.cache_clear()


def test_bot_available_true_with_bot_creds_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Covers the BOT-only branch of ``available`` — web creds stay blank."""
    _blank_click_env(monkeypatch)
    monkeypatch.setenv("CLICK_MERCHANT_ID", "5000")
    monkeypatch.setenv("CLICK_SERVICE_ID_BOT", "108150")
    monkeypatch.setenv("CLICK_SECRET_KEY_BOT", "bot-secret-xyz")
    cfg.get_settings.cache_clear()
    try:
        assert ClickGateway(provider="click_miniapp").available is True
        assert ClickGateway(provider="click").available is False
    finally:
        cfg.get_settings.cache_clear()


def test_available_false_without_merchant_id_even_with_service_and_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``click_merchant_id`` is shared across both surfaces and always required."""
    _blank_click_env(monkeypatch)
    monkeypatch.setenv("CLICK_SERVICE_ID_WEB", "108149")
    monkeypatch.setenv("CLICK_SECRET_KEY_WEB", "web-secret-abc")
    cfg.get_settings.cache_clear()
    try:
        assert ClickGateway(provider="click").available is False
    finally:
        cfg.get_settings.cache_clear()


async def test_create_intent_builds_exact_checkout_url_web(_click_env: None) -> None:
    gw = ClickGateway(provider="click")
    order = SimpleNamespace(id="order-123", currency="UZS", total_charged=Decimal("130000.00"))
    intent = await gw.create_intent(
        db=cast(Any, None), order=order, return_url="https://return.example"
    )

    expected_query = urlencode(
        {
            "service_id": 108149,
            "merchant_id": 5000,
            "amount": Decimal("130000.00"),
            "transaction_param": "order-123",
            "return_url": "https://return.example",
        }
    )
    assert intent.intent_url == f"https://my.click.uz/services/pay?{expected_query}"
    assert intent.external_id == "click:order-123"
    assert intent.status == "pending"
    assert intent.extra_metadata == {"amount_soums": "130000.00"}


async def test_create_intent_builds_exact_checkout_url_bot(_click_env: None) -> None:
    gw = ClickGateway(provider="click_miniapp")
    order = SimpleNamespace(id="order-456", currency="UZS", total_charged=Decimal("50000.00"))
    intent = await gw.create_intent(
        db=cast(Any, None), order=order, return_url="https://t.me/return"
    )

    expected_query = urlencode(
        {
            "service_id": 108150,
            "merchant_id": 5000,
            "amount": Decimal("50000.00"),
            "transaction_param": "order-456",
            "return_url": "https://t.me/return",
        }
    )
    assert intent.intent_url == f"https://my.click.uz/services/pay?{expected_query}"
    assert intent.external_id == "click:order-456"
    assert intent.status == "pending"
    assert intent.extra_metadata == {"amount_soums": "50000.00"}


async def test_create_intent_rejects_non_uzs(_click_env: None) -> None:
    gw = ClickGateway(provider="click")
    order = SimpleNamespace(id="o1", currency="USD", total_charged=Decimal("10"))
    with pytest.raises(PaymentGatewayError, match="UZS"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_create_intent_rejects_non_positive_amount(_click_env: None) -> None:
    gw = ClickGateway(provider="click")
    order = SimpleNamespace(id="o1", currency="UZS", total_charged=Decimal("0"))
    with pytest.raises(PaymentGatewayError, match="non-positive"):
        await gw.create_intent(db=cast(Any, None), order=order, return_url="")


async def test_verify_webhook_not_integrated(_click_env: None) -> None:
    with pytest.raises(PaymentNotIntegratedError, match="payments/click"):
        await ClickGateway(provider="click").verify_webhook(headers={}, body=b"{}")


async def test_refund_refuses(_click_env: None) -> None:
    with pytest.raises(PaymentGatewayError, match="Click"):
        await ClickGateway(provider="click").refund(payment=cast(Any, None), amount=Decimal("1"))


def test_registry_has_both_click_gateways() -> None:
    assert isinstance(REGISTRY["click"], ClickGateway)
    assert REGISTRY["click"].provider == "click"
    assert isinstance(REGISTRY["click_miniapp"], ClickGateway)
    assert REGISTRY["click_miniapp"].provider == "click_miniapp"
