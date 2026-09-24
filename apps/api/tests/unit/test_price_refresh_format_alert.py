"""The supplier price-move alert's escaping, and the low-balance probe.

``_format_alert`` splices supplier/mapping fields (``supplier_slug``,
``external_product_id``, ``external_variant_id``) into a ``parse_mode:HTML``
Telegram message sent by ``notifications.send_admin_alert``. These are
admin/supplier-entered mapping fields, not constants, so a value containing
HTML must come out escaped.
"""

from __future__ import annotations

from decimal import Decimal

from yupay.modules.fulfillment.suppliers import REGISTRY
from yupay.modules.integrations.price_refresh import (
    _WALLET_SUPPLIERS,
    _dollar_balance,
    _format_alert,
)


class _Mapping:
    sku_id = "sku-1"
    supplier_slug = "<script>alert(1)</script>"
    kind = "game"
    external_product_id = '"><img src=x onerror=alert(1)>'
    external_variant_id = "<b>60 UC</b>"


class _Outcome:
    old_cost = Decimal("1.00")
    new_cost = Decimal("1.50")


def test_format_alert_escapes_html_in_mapping_fields() -> None:
    text = _format_alert(mapping=_Mapping(), outcome=_Outcome())

    assert "<script>" not in text
    assert "<img" not in text
    assert "&lt;script&gt;" in text
    assert "&lt;b&gt;60 UC&lt;/b&gt;" in text
    assert "&quot;&gt;&lt;img src=x onerror=alert(1)&gt;" in text


# ---------- the low-balance probe ----------
#
# G2B has had a $50 pre-emptive warning since it was the only supplier we
# funded. G-Engine, NOVA and Waxpeer hold our prepaid money the same way and
# had nothing: their wallet emptying was discovered from failed orders. The
# threshold is one dollar figure for all four, so the only interesting logic
# is which numbers it may be compared against — and that is pure.


def test_a_dollar_balance_is_read() -> None:
    assert _dollar_balance({"available": True, "balance": "12.50", "currency": "USD"}) == 12.5


def test_a_supplier_that_sends_no_currency_is_trusted() -> None:
    # G2B's probe reports USDT and has never carried a `currency` key.
    assert _dollar_balance({"available": True, "balance": 40}) == 40.0


def test_a_currency_the_threshold_does_not_describe_is_refused() -> None:
    # Comparing a soʻm balance to 50 would shout forever; comparing a
    # thousandths-of-a-dollar one would never fire. Silence beats either.
    assert _dollar_balance({"available": True, "balance": "900000", "currency": "UZS"}) is None


def test_a_down_supplier_is_not_an_empty_wallet() -> None:
    # Reachability has its own alerts. A probe that failed says nothing about
    # the money behind it.
    assert _dollar_balance({"available": False, "reason": "timeout"}) is None


def test_an_unreadable_balance_stays_quiet() -> None:
    assert _dollar_balance({"available": True, "balance": None}) is None
    assert _dollar_balance({"available": True, "balance": "n/a"}) is None


def test_every_funded_supplier_is_watched() -> None:
    """The list is the whole feature: a supplier missing from it is a wallet
    nobody is watching, and that is invisible until it empties."""
    assert set(_WALLET_SUPPLIERS) == {"g2b", "gengine", "nova", "waxpeer", "fzr"}
    for slug in _WALLET_SUPPLIERS:
        fulfiller = REGISTRY.get(slug)
        assert fulfiller is not None, slug
        # Probed through the same `health()` the integrations page reads.
        assert hasattr(fulfiller, "health"), slug
