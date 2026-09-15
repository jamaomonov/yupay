"""The Paynet deep link: the half of the integration that leaves our side.

The link's exact shape is the one thing Paynet has not given us yet — host,
parameter names, and whether the amount rides in soʻm or tiyin. So the template
is configuration, and what is worth pinning here is that it *stays*
configuration: the builder must honour whatever placeholders an operator puts
in, and must fail with a sentence rather than a ``KeyError`` when they put in
one we do not supply.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from yupay.core import config as cfg
from yupay.modules.payments.gateways.base import PaymentGatewayError
from yupay.modules.payments.gateways.paynet import PaynetGateway, build_pay_url


@pytest.fixture(autouse=True)
def _paynet_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAYNET_USERNAME", "paynet")
    monkeypatch.setenv("PAYNET_PASSWORD", "secret")
    monkeypatch.setenv("PAYNET_SERVICE_ID", "7")
    cfg.get_settings.cache_clear()
    yield
    cfg.get_settings.cache_clear()


class _Order:
    def __init__(self, total: str = "130000.00", currency: str = "UZS") -> None:
        self.id = "01a0a39a-59cc-7ec2-8d6f-73f2e43b0a46"
        self.currency = currency
        self.total_charged = Decimal(total)


def test_the_default_template_carries_service_amount_and_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del monkeypatch
    url = build_pay_url(order_id="order-1", amount_tiyin=13_000_000)
    assert "provider_id=7" in url
    assert "amount=13000000" in url
    assert "account=order-1" in url


def test_an_operator_can_switch_the_amount_to_major_units(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Their own docs and the third-party write-ups disagree about the unit.
    # Whichever it turns out to be, it must be an env edit.
    monkeypatch.setenv(
        "PAYNET_PAY_URL_TEMPLATE", "paynet://payment?sum={amount_major}&acc={account}"
    )
    cfg.get_settings.cache_clear()
    assert (
        build_pay_url(order_id="o", amount_tiyin=13_000_000) == "paynet://payment?sum=130000&acc=o"
    )


def test_an_unknown_placeholder_fails_with_a_sentence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAYNET_PAY_URL_TEMPLATE", "https://paynet.uz/?merchant={merchant_id}")
    cfg.get_settings.cache_clear()
    with pytest.raises(PaymentGatewayError, match="placeholder"):
        build_pay_url(order_id="o", amount_tiyin=1)


async def test_the_intent_carries_the_link_and_the_exact_tiyin() -> None:
    intent = await PaynetGateway().create_intent(db=None, order=_Order(), return_url="")  # type: ignore[arg-type]
    assert intent.status == "pending"
    assert intent.extra_metadata == {"amount_tiyin": 13_000_000}
    assert intent.intent_url is not None
    assert "account=01a0a39a-59cc-7ec2-8d6f-73f2e43b0a46" in intent.intent_url


async def test_a_non_uzs_order_is_refused() -> None:
    with pytest.raises(PaymentGatewayError, match="UZS"):
        await PaynetGateway().create_intent(db=None, order=_Order(currency="USD"), return_url="")  # type: ignore[arg-type]


async def test_a_sub_tiyin_total_is_refused_rather_than_rounded() -> None:
    # Rounding here would move money by a fraction nobody authorised.
    with pytest.raises(PaymentGatewayError, match="exact tiyin"):
        await PaynetGateway().create_intent(db=None, order=_Order("130000.005"), return_url="")  # type: ignore[arg-type]


def test_the_method_is_unavailable_until_both_halves_are_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A link nobody can settle against takes money into a void, so the
    # credentials gate the checkout button, not just the endpoint.
    assert PaynetGateway().available is True
    monkeypatch.setenv("PAYNET_PASSWORD", "")
    cfg.get_settings.cache_clear()
    assert PaynetGateway().available is False
