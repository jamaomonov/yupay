"""check_player_for_product: mapping resolution, response shaping, cache, PII."""

from __future__ import annotations

from yupay.modules.integrations import player_check as pc


def test_product_is_checkable_true_when_field_has_g2b_check() -> None:
    fields = [{"key": "player_id", "label": {"ru": "ID"}, "type": "text",
               "check": {"provider": "g2b"}}]
    assert pc.product_is_checkable(fields) is True


def test_product_is_checkable_false_without_check() -> None:
    fields = [{"key": "player_id", "label": {"ru": "ID"}, "type": "text"}]
    assert pc.product_is_checkable(fields) is False


def test_map_g2b_response_valid() -> None:
    out = pc._map_response({"valid": "valid", "name": "Neo", "openid": "x"})
    assert out.valid is True
    assert out.name == "Neo"
    assert out.reason is None


def test_map_g2b_response_invalid() -> None:
    out = pc._map_response({"valid": "invalid", "message": "not found"})
    assert out.valid is False
    assert out.name is None
    assert out.reason == "not found"
