"""check_player_for_brand: mapping resolution, response shaping, cache, PII."""

from __future__ import annotations

# Imported first, and as a package rather than reaching straight for
# `integrations.routes`: `check_player_for_brand_id` resolves its supplier
# adapters through a lazy `from ...integrations.routes import ...`, and that
# module's own top-level import of `yupay.api.v1.deps` walks back through
# `yupay.api.v1` -> `integrations.api` -> `integrations.routes` for
# `admin_router`. Whichever test touches that path first pays for the cycle,
# and without this line it is a bare ImportError when this file runs alone —
# green in a full-suite run only because a neighbouring module happened to
# import `yupay.api.v1` earlier. `test_player_check_nova.py` carries the same
# line for the same reason.
import yupay.api.v1  # noqa: F401
from yupay.modules.integrations import player_check as pc


def test_field_of_recognises_a_waxpeer_check_too() -> None:
    """`_field_of`'s known-provider set is `{g2b, waxpeer}`, not just `g2b` —
    the only assertion left that pins Waxpeer in once `product_is_checkable`
    (and its `_checkable_provider` helper) were dropped as dead code."""
    fields = [
        {
            "key": "steam_login",
            "label": {"ru": "Логин Steam"},
            "type": "text",
            "check": {"provider": "waxpeer"},
        }
    ]
    f = pc._field_of(fields)
    assert f is not None
    assert f["key"] == "steam_login"


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


def test_brand_check_field_needs_a_check_on_some_product() -> None:
    assert pc._field_of([{"key": "email", "type": "text"}]) is None
    f = pc._field_of([{"key": "player_id", "type": "text", "check": {"provider": "g2b"}}])
    assert f is not None
    assert f["key"] == "player_id"


def test_brand_check_fields_must_agree_across_products() -> None:
    """Two products of one brand declaring different checks is a misconfiguration:
    a brand-level check would have to pick one, and picking is guessing."""
    a = {"key": "player_id", "type": "text", "check": {"provider": "g2b"}}
    b = {"key": "player_id", "type": "text", "check": {"provider": "g2b", "server_field": "server"}}
    assert pc._agreed_field([a, a]) is a
    assert pc._agreed_field([a, b]) is None


# --- wiring the NOVA fallback into check_player_for_brand_id -----------------


class _FakeSlugSession:
    """Just enough of ``AsyncSession`` for the ``Brand.slug`` read
    ``check_player_for_brand_id`` does.

    That read happens **after** the G2B round trip, on the ``error`` branch
    only: reading it up front costs a query on every check and broke a pinned
    SQL-count regression. The session is still usable there — the rollback
    before the supplier call returns the connection, and SQLAlchemy simply
    begins a new transaction when this asks it to.
    """

    def __init__(self, slug: str | None) -> None:
        self._slug = slug
        #: Whether a transaction is open right now. A query autobegins one; only
        #: a rollback ends it. Modelling that is the whole point of this double
        #: — see `test_the_fallback_is_not_called_holding_a_connection`.
        self.in_transaction = False

    async def execute(self, _stmt: object) -> _FakeSlugSession:
        self.in_transaction = True
        return self

    def scalar_one_or_none(self) -> str | None:
        return self._slug

    async def rollback(self) -> None:
        self.in_transaction = False


def _fixed_field(field: dict[str, object]):  # type: ignore[no-untyped-def]
    """A ``brand_check_field`` stand-in that always answers the same field,
    so these tests exercise only the ``error`` dispatch, not mapping lookup."""

    async def _f(session: object, brand_id: str) -> dict:  # type: ignore[type-arg]
        return field

    return _f


async def test_primary_valid_never_consults_nova(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(pc, "brand_check_field", _fixed_field({"check": {"provider": "g2b"}}))
    calls = {"nova": 0}

    async def fake_g2b(session, *, brand_id, player_id, server_id):  # type: ignore[no-untyped-def]
        return pc.PlayerCheckOut(status="valid", name="Neo")

    async def fake_nova_brand(brand_slug, player_id, server_id):  # type: ignore[no-untyped-def]
        calls["nova"] += 1
        return pc.PlayerCheckOut(status="valid")

    monkeypatch.setattr(pc, "_check_g2b_player", fake_g2b)
    monkeypatch.setattr(pc, "_nova_brand", fake_nova_brand)

    out = await pc.check_player_for_brand_id(
        _FakeSlugSession("mobile-legends-ru"),  # type: ignore[arg-type]
        brand_id="b1",
        player_id="p1",
        server_id=None,
    )

    assert out.status == "valid"
    assert out.name == "Neo"
    assert calls["nova"] == 0, "a real verdict is never second-guessed"


async def test_primary_invalid_never_consults_nova(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The customer's mistake is already known; NOVA has nothing to add."""
    monkeypatch.setattr(pc, "brand_check_field", _fixed_field({"check": {"provider": "g2b"}}))
    calls = {"nova": 0}

    async def fake_g2b(session, *, brand_id, player_id, server_id):  # type: ignore[no-untyped-def]
        return pc.PlayerCheckOut(status="invalid")

    async def fake_nova_brand(brand_slug, player_id, server_id):  # type: ignore[no-untyped-def]
        calls["nova"] += 1
        return pc.PlayerCheckOut(status="valid")

    monkeypatch.setattr(pc, "_check_g2b_player", fake_g2b)
    monkeypatch.setattr(pc, "_nova_brand", fake_nova_brand)

    out = await pc.check_player_for_brand_id(
        _FakeSlugSession("mobile-legends-ru"),  # type: ignore[arg-type]
        brand_id="b1",
        player_id="p1",
        server_id=None,
    )

    assert out.status == "invalid"
    assert calls["nova"] == 0


async def test_the_fallback_is_not_called_holding_a_connection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The property the rollback before a supplier call exists to protect.

    The pool is twenty connections for the whole process and a healthy check
    takes up to five seconds, so a supplier call made while holding one is how
    a slow supplier becomes an outage — the reasoning `_check_g2b_player`
    already writes down at its own rollback. The brand-slug read on the error
    branch autobegins a *new* transaction after that rollback, so the fallback
    would have run holding a connection unless the branch hands it back too.

    Nothing else catches this: the query-count regression test only counts
    statements on the happy path, and no test in this repo asserted the
    rollback property for any supplier.
    """
    monkeypatch.setattr(pc, "brand_check_field", _fixed_field({"check": {"provider": "g2b"}}))
    session = _FakeSlugSession("mobile-legends-ru")
    seen: dict[str, bool] = {}

    async def fake_g2b(session_, *, brand_id, player_id, server_id):  # type: ignore[no-untyped-def]
        # The real one rolls back before its own supplier call; model that.
        await session_.rollback()
        return pc.PlayerCheckOut(status="error")

    async def fake_nova_brand(brand_slug, player_id, server_id):  # type: ignore[no-untyped-def]
        seen["in_transaction"] = session.in_transaction
        return pc.PlayerCheckOut(status="valid", name="blood moon")

    monkeypatch.setattr(pc, "_check_g2b_player", fake_g2b)
    monkeypatch.setattr(pc, "_nova_brand", fake_nova_brand)

    await pc.check_player_for_brand_id(
        session,  # type: ignore[arg-type]
        brand_id="b1",
        player_id="p1",
        server_id=None,
    )

    assert seen["in_transaction"] is False, (
        "the brand-slug read reopened a transaction and the NOVA call was made "
        "while holding the connection"
    )


async def test_the_fallback_releases_even_when_g2b_returned_early(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The exits that never reach `_check_g2b_player`'s own rollback.

    It answers `error` immediately when the brand has no active G2B mapping or
    when the adapter is unconfigured, and the first of those is a routine,
    permanent state for a brand — not an outage-only path. So the release on
    this branch has to stand on its own rather than lean on that one.
    """
    monkeypatch.setattr(pc, "brand_check_field", _fixed_field({"check": {"provider": "g2b"}}))
    session = _FakeSlugSession("mobile-legends-ru")
    session.in_transaction = True  # as if a caller's read left one open
    seen: dict[str, bool] = {}

    async def fake_g2b(session_, *, brand_id, player_id, server_id):  # type: ignore[no-untyped-def]
        return pc.PlayerCheckOut(status="error")  # early exit: no rollback

    async def fake_nova_brand(brand_slug, player_id, server_id):  # type: ignore[no-untyped-def]
        seen["in_transaction"] = session.in_transaction
        return pc.PlayerCheckOut(status="error")

    monkeypatch.setattr(pc, "_check_g2b_player", fake_g2b)
    monkeypatch.setattr(pc, "_nova_brand", fake_nova_brand)

    await pc.check_player_for_brand_id(
        session,  # type: ignore[arg-type]
        brand_id="b1",
        player_id="p1",
        server_id=None,
    )

    assert seen["in_transaction"] is False


async def test_a_steam_login_error_consults_nova_too(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The Waxpeer half of the same dispatch.

    `fallback_for_steam` has unit tests of its own, but the one line that
    reaches it had none — and a `return out` there would have left the suite
    green while the Steam fallback never ran.
    """
    monkeypatch.setattr(pc, "brand_check_field", _fixed_field({"check": {"provider": "waxpeer"}}))
    calls = {"nova": 0, "brand": 0}

    async def fake_waxpeer(_fulfiller, *, steam_login):  # type: ignore[no-untyped-def]
        return pc.PlayerCheckOut(status="error")

    async def fake_nova_steam(steam_login):  # type: ignore[no-untyped-def]
        calls["nova"] += 1
        assert steam_login == "someone"
        return pc.PlayerCheckOut(status="valid")

    async def fake_nova_brand(brand_slug, player_id, server_id):  # type: ignore[no-untyped-def]
        calls["brand"] += 1
        return pc.PlayerCheckOut(status="error")

    monkeypatch.setattr(pc, "_check_waxpeer_login", fake_waxpeer)
    monkeypatch.setattr(pc, "_waxpeer_fulfiller_or_none", lambda: None, raising=False)
    monkeypatch.setattr(pc, "_nova_steam", fake_nova_steam)
    monkeypatch.setattr(pc, "_nova_brand", fake_nova_brand)

    out = await pc.check_player_for_brand_id(
        _FakeSlugSession("steam"),  # type: ignore[arg-type]
        brand_id="b1",
        player_id="someone",
        server_id=None,
    )

    assert out.status == "valid"
    assert calls["nova"] == 1
    # The brand fallback is for a game brand; a Steam login must not reach it.
    assert calls["brand"] == 0


async def test_a_steam_login_verdict_is_never_second_guessed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(pc, "brand_check_field", _fixed_field({"check": {"provider": "waxpeer"}}))
    calls = {"nova": 0}

    async def fake_waxpeer(_fulfiller, *, steam_login):  # type: ignore[no-untyped-def]
        return pc.PlayerCheckOut(status="invalid")

    async def fake_nova_steam(steam_login):  # type: ignore[no-untyped-def]
        calls["nova"] += 1
        return pc.PlayerCheckOut(status="valid")

    monkeypatch.setattr(pc, "_check_waxpeer_login", fake_waxpeer)
    monkeypatch.setattr(pc, "_waxpeer_fulfiller_or_none", lambda: None, raising=False)
    monkeypatch.setattr(pc, "_nova_steam", fake_nova_steam)

    out = await pc.check_player_for_brand_id(
        _FakeSlugSession("steam"),  # type: ignore[arg-type]
        brand_id="b1",
        player_id="someone",
        server_id=None,
    )

    assert out.status == "invalid"
    assert calls["nova"] == 0


async def test_primary_error_consults_nova_once_and_its_valid_wins(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """The one case the fallback exists for: no verdict at all from the primary."""
    monkeypatch.setattr(pc, "brand_check_field", _fixed_field({"check": {"provider": "g2b"}}))
    calls = {"nova": 0}

    async def fake_g2b(session, *, brand_id, player_id, server_id):  # type: ignore[no-untyped-def]
        return pc.PlayerCheckOut(status="error")

    async def fake_nova_brand(brand_slug, player_id, server_id):  # type: ignore[no-untyped-def]
        calls["nova"] += 1
        assert brand_slug == "mobile-legends-ru", "the fallback is keyed by brand"
        return pc.PlayerCheckOut(status="valid", name="blood moon")

    monkeypatch.setattr(pc, "_check_g2b_player", fake_g2b)
    monkeypatch.setattr(pc, "_nova_brand", fake_nova_brand)

    out = await pc.check_player_for_brand_id(
        _FakeSlugSession("mobile-legends-ru"),  # type: ignore[arg-type]
        brand_id="b1",
        player_id="p1",
        server_id=None,
    )

    assert out.status == "valid"
    assert out.name == "blood moon"
    assert calls["nova"] == 1
