"""Unit tests for wallet top-up amount / provider rules (ADR-0058)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from yupay.core.errors import ValidationError
from yupay.modules.wallet.topup_limits import currency_for_provider, quantize_topup_amount


def test_click_family_is_uzs() -> None:
    assert currency_for_provider("click") == "UZS"
    assert currency_for_provider("click_miniapp") == "UZS"
    assert currency_for_provider("payme") == "UZS"
    assert currency_for_provider("uzum") == "UZS"


def test_crypto_is_usdt() -> None:
    assert currency_for_provider("crypto") == "USDT"


def test_wallet_provider_is_refused() -> None:
    with pytest.raises(ValidationError, match="paying from the wallet"):
        currency_for_provider("wallet")


def test_unknown_provider_is_refused() -> None:
    with pytest.raises(ValidationError, match="cannot fund"):
        currency_for_provider("yookassa")


def test_uzs_accepts_whole_som_in_range() -> None:
    assert quantize_topup_amount(Decimal("10000"), "UZS") == Decimal("10000")
    assert quantize_topup_amount(Decimal("5000000"), "UZS") == Decimal("5000000")


def test_uzs_rejects_fractional() -> None:
    with pytest.raises(ValidationError, match="quantum"):
        quantize_topup_amount(Decimal("10000.5"), "UZS")


def test_uzs_rejects_below_min() -> None:
    with pytest.raises(ValidationError, match="below the minimum"):
        quantize_topup_amount(Decimal("9999"), "UZS")


def test_usdt_accepts_cents() -> None:
    assert quantize_topup_amount(Decimal("5.01"), "USDT") == Decimal("5.01")


def test_usdt_rejects_below_five() -> None:
    with pytest.raises(ValidationError, match="below the minimum"):
        quantize_topup_amount(Decimal("4.99"), "USDT")
