"""The recipient a reseller sent with an order, labelled for the cabinet."""

from __future__ import annotations

from yupay.modules.merchants.recipient import recipient_fields, recipient_summary

PLAYER = {
    "key": "player_id",
    "type": "text",
    "label": {"ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID"},
}
SERVER = {
    "key": "server",
    "type": "select",
    "label": {"ru": "Сервер", "en": "Server", "uz": "Server"},
    "options": [{"value": "2045", "label": {"ru": "Азия", "en": "Asia", "uz": "Osiyo"}}],
}


def test_labels_each_value_with_its_form_field_in_form_order() -> None:
    out = recipient_fields({"server": "2045", "player_id": "123456"}, [PLAYER, SERVER])

    assert [(f.key, f.value) for f in out] == [("player_id", "123456"), ("server", "2045")]
    assert out[0].label == PLAYER["label"]
    assert out[0].value_label is None
    assert out[1].value_label == {"ru": "Азия", "en": "Asia", "uz": "Osiyo"}


def test_skips_keys_the_form_does_not_define_and_empty_values() -> None:
    out = recipient_fields({"player_id": "  ", "zone": "1", "server": "2045"}, [PLAYER, SERVER])

    assert [f.key for f in out] == ["server"]


def test_never_returns_a_trade_link() -> None:
    link = {"key": "tradelink", "type": "text", "label": {"ru": "Трейд-ссылка"}}

    assert recipient_fields({"tradelink": "https://x/?partner=1&token=s"}, [link]) == []


def test_tolerates_missing_data_and_a_malformed_form() -> None:
    assert recipient_fields(None, [PLAYER]) == []
    assert recipient_fields({"player_id": "1"}, None) == []
    assert recipient_fields({"player_id": "1"}, [{"type": "text"}, "junk"]) == []


def test_unknown_select_value_keeps_the_raw_value() -> None:
    out = recipient_fields({"server": "9999"}, [SERVER])

    assert out[0].value == "9999"
    assert out[0].value_label is None


def test_summary_joins_display_values_for_the_list_row() -> None:
    fields = recipient_fields({"player_id": "123456", "server": "2045"}, [PLAYER, SERVER])

    assert recipient_summary(fields, "ru") == "123456 · Азия"
    assert recipient_summary([], "ru") is None
