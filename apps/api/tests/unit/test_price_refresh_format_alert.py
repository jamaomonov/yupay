"""HTML-escaping check for the supplier price-move ops alert.

``_format_alert`` splices supplier/mapping fields (``supplier_slug``,
``external_product_id``, ``external_variant_id``) into a ``parse_mode:HTML``
Telegram message sent by ``notifications.send_admin_alert``. These are
admin/supplier-entered mapping fields, not constants, so a value containing
HTML must come out escaped.
"""

from __future__ import annotations

from decimal import Decimal

from yupay.modules.integrations.price_refresh import _format_alert


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
