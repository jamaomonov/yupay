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


def test_map_g2b_response_unexpected_body_is_error_not_invalid() -> None:
    """A shape we cannot read is "we could not check", never "no such player".

    This assertion is the reverse of the one it replaces, which read: "a 200
    with an unexpected shape still means the id didn't resolve, which is the
    customer's problem (invalid), not our fault (error)." That was wrong, and
    wrong in the direction this whole three-way status exists to prevent —
    only mirrored. `invalid` is published (module README, `/merchant/v1`) as
    the one answer meaning the customer mistyped, so mapping an unreadable
    body to it makes the check a fake **rejecter**: if G2B renamed `valid`,
    every call would be a 200, no breaker would fire, nothing would log a
    failure, and every player id on the platform would come back "no such
    player". The empty body below is the cheapest instance of that shape.
    """
    assert pc._map_response({}).status == "error"


def test_map_g2b_response_unknown_verdict_token_is_error() -> None:
    """A third token nobody told us about is not a verdict either."""
    assert pc._map_response({"valid": "maybe"}).status == "error"


def test_map_g2b_response_renamed_verdict_key_is_error() -> None:
    """The failure scenario in full: the field moves and the body still parses."""
    assert pc._map_response({"is_valid": "valid", "name": "Neo"}).status == "error"


def test_map_g2b_response_tolerates_case_and_padding_on_a_real_verdict() -> None:
    """Strictness is about *recognising* the token, not about punishing whitespace."""
    assert pc._map_response({"valid": " VALID ", "name": "Neo"}).status == "valid"
    assert pc._map_response({"valid": "Invalid"}).status == "invalid"


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


class _FakeRedis:
    """Just enough of the client the check uses: ``get`` / ``set`` with a TTL."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


class _ScriptedWaxpeer:
    """A fulfiller whose client answers ``validate_login`` from a script."""

    def __init__(self, answers: list[tuple[bool, str | None]]) -> None:
        self._answers = list(answers)
        self.calls = 0

    def _client(self) -> _ScriptedWaxpeer:
        return self

    async def validate_login(self, steam_login: str) -> tuple[bool, str | None]:
        self.calls += 1
        return self._answers.pop(0)


async def test_a_negative_waxpeer_verdict_is_not_remembered(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Waxpeer has answered ``valid: false`` for a login it accepts a moment later.

    Observed on the owner's own valid login. A verdict is the supplier's word at
    one instant; only ``invalid`` blocks Pay, so remembering a wrong one turns a
    supplier hiccup into a five-minute dead checkout that a re-check cannot
    clear — the storefront asks again, and we answer from the cache.
    """
    fake = _FakeRedis()
    monkeypatch.setattr(pc, "get_redis", lambda: fake)
    supplier = _ScriptedWaxpeer([(False, "Steam profile not found"), (True, None)])

    first = await pc._check_waxpeer_login(supplier, steam_login="jama")
    assert first.status == "invalid"
    assert fake.store == {}, "a negative is never written"

    second = await pc._check_waxpeer_login(supplier, steam_login="jama")
    assert second.status == "valid", "the re-check reached the supplier"
    assert supplier.calls == 2


async def test_a_positive_waxpeer_verdict_is_remembered(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The cache still earns its keep on the answer that is safe to keep:
    # repeat taps on a good login stay off the supplier.
    fake = _FakeRedis()
    monkeypatch.setattr(pc, "get_redis", lambda: fake)
    supplier = _ScriptedWaxpeer([(True, None)])

    assert (await pc._check_waxpeer_login(supplier, steam_login="jama")).status == "valid"
    assert len(fake.store) == 1
    assert (await pc._check_waxpeer_login(supplier, steam_login="jama")).status == "valid"
    assert supplier.calls == 1, "served from the cache"
