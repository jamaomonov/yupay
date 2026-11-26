"""The UzQR and P2P gateways refuse what they cannot take, before any call out.

Both are UZS-only, both need a window long enough to pay in, and neither has a
webhook or a refund API. Each refusal's message is what the storefront shows,
so each one is pinned here.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from yupay.core.clock import now
from yupay.core.errors import ConflictError, UpstreamUnavailableError
from yupay.modules.payments.gateways.base import (
    PaymentGatewayError,
    PaymentNotIntegratedError,
)
from yupay.modules.payments.gateways.p2p import P2PGateway
from yupay.modules.payments.gateways.uzqr import UzqrGateway
from yupay.modules.uzqr import client as uzqr_client

pytestmark = pytest.mark.asyncio


def _order(*, currency: str = "UZS", total: str = "15000", minutes: int = 15) -> Any:
    return SimpleNamespace(
        id="order-1",
        currency=currency,
        total_charged=total,
        expires_at=now() + timedelta(minutes=minutes),
    )


async def _intent(gateway: Any, order: Any) -> Any:
    return await gateway.create_intent(db=None, order=order, return_url="https://x")


@pytest.mark.parametrize("gateway_cls", [UzqrGateway, P2PGateway])
@pytest.mark.parametrize(
    ("order", "match"),
    [
        (_order(currency="USD"), "only supports UZS"),
        (_order(total="0"), "order total must be a positive"),
        (_order(minutes=0), "слишком мало времени"),
    ],
)
async def test_an_order_it_cannot_take_is_refused(
    gateway_cls: type[Any], order: Any, match: str
) -> None:
    with pytest.raises(PaymentGatewayError, match=match):
        await _intent(gateway_cls(), order)


async def test_uzqr_refuses_a_fraction_of_a_tiyin() -> None:
    with pytest.raises(PaymentGatewayError, match="tiyin"):
        await _intent(UzqrGateway(), _order(total="100.005"))


async def test_p2p_refuses_a_fraction_of_a_sum() -> None:
    with pytest.raises(PaymentGatewayError, match="whole number"):
        await _intent(P2PGateway(), _order(total="100.50"))


@pytest.mark.parametrize(
    ("exc", "match"),
    [
        (uzqr_client.UzqrError("refused", code=1, http_status=400), "недоступна"),
        (uzqr_client.UzqrUnavailableError("timeout"), "не отвечает"),
    ],
)
async def test_uzqr_says_why_no_invoice_was_made(
    monkeypatch: pytest.MonkeyPatch, exc: Exception, match: str
) -> None:
    async def _refuse(**_: Any) -> Any:
        raise exc

    monkeypatch.setattr(uzqr_client, "create_invoice", _refuse)
    with pytest.raises(PaymentGatewayError, match=match):
        await _intent(UzqrGateway(), _order())


@pytest.mark.parametrize("gateway_cls", [UzqrGateway, P2PGateway])
async def test_there_is_no_webhook_and_no_refund_api(gateway_cls: type[Any]) -> None:
    gateway = gateway_cls()
    with pytest.raises(PaymentNotIntegratedError):
        await gateway.verify_webhook(headers={}, body=b"")
    with pytest.raises(PaymentGatewayError, match="manual"):
        await gateway.refund(payment=None, amount=Decimal("1"))


@pytest.mark.parametrize(
    ("exc", "match"),
    [
        (ConflictError("no card fits"), "недоступен для этой суммы"),
        (UpstreamUnavailableError("held"), "занят"),
    ],
)
async def test_p2p_says_why_no_card_was_reserved(
    monkeypatch: pytest.MonkeyPatch, exc: Exception, match: str
) -> None:
    from yupay.modules.p2p import reservations
    from yupay.modules.p2p import settings as p2p_settings

    async def _connected(_db: Any) -> Any:
        return SimpleNamespace(business_connection_id="bc-1")

    async def _refuse(*_: Any, **__: Any) -> Any:
        raise exc

    monkeypatch.setattr(p2p_settings, "load_settings", _connected)
    monkeypatch.setattr(reservations, "reserve_for_order", _refuse)
    with pytest.raises(PaymentGatewayError, match=match):
        await _intent(P2PGateway(), _order())
