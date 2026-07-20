"""check_player_for_product: mapping resolution, response shaping, cache, PII."""

from __future__ import annotations

from yupay.modules.integrations import player_check as pc


def test_product_is_checkable_true_when_field_has_g2b_check() -> None:
    fields = [
        {"key": "player_id", "label": {"ru": "ID"}, "type": "text", "check": {"provider": "g2b"}}
    ]
    assert pc.product_is_checkable(fields) is True


def test_product_is_checkable_false_without_check() -> None:
    fields = [{"key": "player_id", "label": {"ru": "ID"}, "type": "text"}]
    assert pc.product_is_checkable(fields) is False


def test_product_is_checkable_true_when_field_has_waxpeer_check() -> None:
    fields = [
        {
            "key": "steam_login",
            "label": {"ru": "Логин Steam"},
            "type": "text",
            "check": {"provider": "waxpeer"},
        }
    ]
    assert pc.product_is_checkable(fields) is True


def test_map_g2b_response_valid() -> None:
    out = pc._map_response({"valid": "valid", "name": "Neo", "openid": "x"})
    assert out.status == "valid"
    assert out.name == "Neo"


def test_map_g2b_response_invalid() -> None:
    out = pc._map_response({"valid": "invalid", "message": "not found"})
    assert out.status == "invalid"
    assert out.name is None


def test_map_g2b_response_unexpected_body_is_invalid_not_error() -> None:
    # A 200 with an unexpected shape still means "the id didn't resolve",
    # which is the customer's problem (invalid), not our fault (error).
    out = pc._map_response({})
    assert out.status == "invalid"


def test_cache_key_does_not_embed_raw_player_id() -> None:
    key = pc._cache_key("pubgm", "51234567", None)
    assert "51234567" not in key


def test_cache_key_is_deterministic() -> None:
    assert pc._cache_key("pubgm", "51234567", None) == pc._cache_key("pubgm", "51234567", None)
    assert pc._cache_key("pubgm", "51234567", "srv1") == pc._cache_key("pubgm", "51234567", "srv1")


def test_waxpeer_cache_key_does_not_embed_raw_login() -> None:
    key = pc._waxpeer_cache_key("gaben")
    assert "gaben" not in key


def test_waxpeer_cache_key_is_deterministic() -> None:
    assert pc._waxpeer_cache_key("gaben") == pc._waxpeer_cache_key("gaben")


def test_waxpeer_cache_key_differs_from_g2b_cache_key_namespace() -> None:
    # Different providers must never collide on the same Redis key even if a
    # g2b player_id and a Steam login happened to be equal strings.
    assert pc._waxpeer_cache_key("51234567") != pc._cache_key("pubgm", "51234567", None)
