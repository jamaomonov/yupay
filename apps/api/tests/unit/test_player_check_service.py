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


# --- which failures are the breaker's business -------------------------------


def test_a_broken_game_mapping_does_not_count_against_the_supplier() -> None:
    """One brand's bad `game_code` must not silence checks for the other
    sixteen.

    G2B answers an unknown game with a non-retryable 4xx, which the client
    raises immediately — there is no backoff to save, so counting it buys
    nothing and costs a shared circuit. The breaker exists to stop customers
    paying the retry budget, not to react to every error.
    """
    from yupay.modules.fulfillment.suppliers.g2b_client import G2bError

    assert pc._counts_against_supplier(G2bError(400, "unknown game")) is False
    assert pc._counts_against_supplier(G2bError(404, "not found")) is False


def test_retries_exhausted_counts() -> None:
    """The case the breaker was built for: ~15s of backoff to reach `error`."""
    from yupay.core.errors import UpstreamUnavailableError

    assert pc._counts_against_supplier(UpstreamUnavailableError("g2b network error")) is True


def test_a_bad_api_key_counts_even_though_it_fails_fast() -> None:
    """401 costs the customer nothing — it is counted to protect *fulfilment*.

    The client's own comment is explicit that a few 401s in a row get our IP
    banned at G2B, and that ban would take order delivery down with it. So the
    advisory path must stop hammering a rejected key, even though no customer
    is waiting on it.
    """
    from yupay.modules.fulfillment.suppliers.g2b_client import G2bError

    assert pc._counts_against_supplier(G2bError(401, "unauthorized")) is True


def test_an_unexpected_error_counts() -> None:
    """Unknown failures are treated as supplier trouble: the alternative is a
    new exception type silently disabling the breaker."""
    assert pc._counts_against_supplier(RuntimeError("dns exploded")) is True
