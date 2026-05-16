"""Payment gateway registry.

Add a new provider:
  1. Implement ``PaymentGateway`` (see :mod:`yupay.modules.payments.gateways.base`).
  2. Drop the implementation into a new file under this package.
  3. Register it in :data:`REGISTRY` below.

Stubs (``click``, ``payme``, ``uzum``, ``yookassa``, ``tinkoff``, ``crypto``) keep
their slugs reserved so the routes / webhooks / admin UI don't shift when the real
implementation arrives.
"""

from __future__ import annotations

from yupay.core.errors import NotFoundError
from yupay.modules.payments.gateways._stub import StubGateway
from yupay.modules.payments.gateways.base import (
    PaymentGateway,
    PaymentGatewayError,
    PaymentIntent,
    PaymentNotIntegratedError,
    RefundResult,
    WebhookEvent,
)
from yupay.modules.payments.gateways.mock import MockGateway

REGISTRY: dict[str, PaymentGateway] = {
    "mock": MockGateway(),
    # --- Uzbek acquirers ---
    "click": StubGateway(
        provider="click",
        todo_message="Click acquirer not integrated yet; see ADR-0012.",
    ),
    "payme": StubGateway(
        provider="payme",
        todo_message="Payme acquirer not integrated yet; see ADR-0012.",
    ),
    "uzum": StubGateway(
        provider="uzum",
        todo_message="Uzum acquirer not integrated yet; see ADR-0012.",
    ),
    # --- Russian acquirers ---
    "yookassa": StubGateway(
        provider="yookassa",
        todo_message="YooKassa acquirer not integrated yet; see ADR-0012.",
    ),
    "tinkoff": StubGateway(
        provider="tinkoff",
        todo_message="Tinkoff acquirer not integrated yet; see ADR-0012.",
    ),
    # --- Crypto ---
    "crypto": StubGateway(
        provider="crypto",
        todo_message="Crypto acquirer not integrated yet; see ADR-0012.",
    ),
}


def get_gateway(provider: str) -> PaymentGateway:
    """Look up a gateway by slug. 404 if unknown."""
    gw = REGISTRY.get(provider.lower())
    if gw is None:
        raise NotFoundError(f"unknown payment provider: {provider}")
    return gw


def available_providers() -> list[str]:
    """List provider slugs that can actually serve requests right now."""
    return [slug for slug, gw in REGISTRY.items() if gw.available]


__all__ = [
    "REGISTRY",
    "MockGateway",
    "PaymentGateway",
    "PaymentGatewayError",
    "PaymentIntent",
    "PaymentNotIntegratedError",
    "RefundResult",
    "StubGateway",
    "WebhookEvent",
    "available_providers",
    "get_gateway",
]
