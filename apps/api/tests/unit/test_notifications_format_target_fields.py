"""HTML-escaping check for fulfilment-data fields shown in the delivered alert.

``_format_target_fields`` splices the customer's checkout free text (e.g.
whatever they typed as a player id) into a ``parse_mode:HTML`` Telegram
message. Both the value and the label (which falls back to the raw,
non-constant field key when it isn't a known label) must come out escaped.
"""

from __future__ import annotations

from yupay.modules.notifications.service import _format_target_fields, review_webapp_markup


def test_format_target_fields_escapes_html_in_value() -> None:
    result = _format_target_fields({"player_id": "<b>1337</b>"})
    assert result is not None
    assert "<b>1337</b>" not in result
    assert "&lt;b&gt;1337&lt;/b&gt;" in result


def test_format_target_fields_escapes_html_in_unknown_label_key() -> None:
    """A key outside ``_FIELD_LABEL_RU`` is used verbatim as the label —
    it must be escaped too since it isn't a compile-time constant."""
    result = _format_target_fields({"<script>alert(1)</script>": "value"})
    assert result is not None
    assert "<script>" not in result
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in result


def test_format_target_fields_known_label_renders_in_russian() -> None:
    result = _format_target_fields({"player_id": "123"})
    assert result == "ID игрока: <code>123</code>"


def test_review_webapp_markup_pins_the_order_on_the_miniapp_url() -> None:
    order_id = "11111111-1111-1111-1111-111111111111"
    markup = review_webapp_markup(order_id)
    assert markup is not None
    button = markup["inline_keyboard"][0][0]
    assert button["text"] == "Оценить заказ"
    assert f"review={order_id}" in button["web_app"]["url"]
