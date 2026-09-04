"""HTTP tests for the pre-purchase Steam profile check (`POST /gifts/steam-profile`).

Covers every case the task brief lists:
- a `/profiles/` link returns `found` with nickname+avatar and makes no
  `ResolveVanityURL` call at all;
- an `/id/{vanity}` link resolves first, then summarises;
- an unknown vanity is `not_found`;
- an `s.team` link is `unsupported` with no Steam call at all;
- a missing API key is `unavailable`;
- a Steam timeout is `unavailable`;
- the `steam_gifts_enabled` flag being off 404s like the rest of the router;
- a second identical call is served from the Redis cache (one upstream call).

Plus, from fix round 1 review:
- `GetPlayerSummaries` coming back empty is `unavailable`, not `found`, for
  *both* link shapes -- a `found` with nothing to render confirms nothing;
- a Steam 4xx/5xx never leaks `STEAM_API_KEY` (embedded in the query string
  of every request this module makes) into the structured logs;
- a malformed/stale blob under the cache key degrades like a cache miss,
  never a 500.

Plus, from the final whole-branch review:
- the cache key is namespaced by link shape: every steamid64 is also a
  syntactically valid vanity name, so one namespace meant a `not_found` filed
  for `/id/{17 digits}` answered for `/profiles/{same digits}` -- a six-hour
  denial of purchase against any Steam account, from one unauthenticated
  request, and in the other direction a stranger's card shown as the
  recipient;
- `GetPlayerSummaries` answering 200 with an empty `players` array is Steam's
  definitive "no such account" and reads as `not_found`, distinct from any
  failure to ask, which stays `unavailable`.

Plus, from P2's fix round 1 review:
- the link travels in the request body, never a query string: Caddy's access
  log records `uri` verbatim and promtail ships it to Loki, so a `GET
  ...?invite_url=steamcommunity.com/id/{vanity}` would park a third party's
  identity in the logs. `test_a_get_with_the_link_in_the_query_string_is_405`
  is what stops a future refactor quietly putting it back.

`@respx.mock` blocks any unmocked outbound request by raising, which is what
makes "makes no resolve call" / "no Steam call at all" real assertions rather
than just an absence of a positive check.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
import respx
import structlog.testing
from httpx import AsyncClient
from yupay.core import config as cfg
from yupay.core.redis import get_redis
from yupay.modules.gifts import profile as profile_mod
from yupay.modules.gifts.schemas import GiftProfileOut

pytestmark = pytest.mark.asyncio

_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
_RESOLVE_URL = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"

_STEAM_ID = "76561198000000123"
_PROFILE_LINK = f"https://steamcommunity.com/profiles/{_STEAM_ID}"
_VANITY_LINK = "https://steamcommunity.com/id/my_vanity-01"
_S_TEAM_LINK = "https://s.team/p/abcXYZ"


@pytest.fixture(autouse=True)
def _settings_cache_teardown():
    """Undo `_enable`'s `lru_cache` clear once the test is over.

    `monkeypatch` restores the environment after each test but knows nothing
    about the `lru_cache` built from it, so every `_enable` below leaves this
    file's settings object installed for whatever runs next in the same
    worker — including its `AUTH_IP_GUARD_BUCKET_MAX` override, which drops
    `check_player` from 200 to the default. An ordering-dependent flake under
    xdist, and this was the only gifts test file without the guard: see
    `test_gifts_catalog_routes.py` and `test_checkout_steam_gift.py` for the
    same fixture.
    """
    yield
    cfg.get_settings.cache_clear()


def _enable(monkeypatch: pytest.MonkeyPatch, *, api_key: str | None = "test-steam-key") -> None:
    monkeypatch.setenv("STEAM_GIFTS_ENABLED", "true")
    if api_key is None:
        monkeypatch.delenv("STEAM_API_KEY", raising=False)
    else:
        monkeypatch.setenv("STEAM_API_KEY", api_key)
    cfg.get_settings.cache_clear()


def _summaries_payload(
    *, name: str = "jama", avatar: str = "https://cdn.example/a.jpg"
) -> dict[str, Any]:
    return {"response": {"players": [{"personaname": name, "avatarfull": avatar}]}}


async def _check(client: AsyncClient, invite_url: str) -> httpx.Response:
    """POST, not GET -- the link is a third party's identity and a query
    string is logged verbatim at the edge. See ``GiftProfileIn``."""
    return await client.post("/api/v1/gifts/steam-profile", json={"invite_url": invite_url})


# ---------- the enabled guard ----------


async def test_disabled_flag_404s(integration_client: AsyncClient) -> None:
    """`steam_gifts_enabled` defaults to False; this route is no exception."""
    r = await _check(integration_client, _PROFILE_LINK)
    assert r.status_code == 404, r.text


# ---------- /profiles/{steamid64} ----------


@respx.mock
async def test_profiles_link_is_found_with_no_resolve_call(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(_SUMMARIES_URL).mock(return_value=httpx.Response(200, json=_summaries_payload()))
    # No _RESOLVE_URL mock armed: respx would refuse an unmocked call, so a
    # ResolveVanityURL request here would fail the test outright.

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "found"
    assert body["steam_id"] == _STEAM_ID
    assert body["nickname"] == "jama"
    assert body["avatar_url"] == "https://cdn.example/a.jpg"


# ---------- /id/{vanity} ----------


@respx.mock
async def test_vanity_link_resolves_then_summarises(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 1, "steamid": _STEAM_ID}})
    )
    respx.get(_SUMMARIES_URL).mock(return_value=httpx.Response(200, json=_summaries_payload()))

    r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "found"
    assert body["steam_id"] == _STEAM_ID
    assert body["nickname"] == "jama"


@respx.mock
async def test_unknown_vanity_is_not_found(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 42, "message": "No match"}})
    )
    # No _SUMMARIES_URL mock armed: a not_found vanity must never reach
    # GetPlayerSummaries at all.

    r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "not_found"
    assert body["steam_id"] is None
    assert body["nickname"] is None
    assert body["avatar_url"] is None


@respx.mock
async def test_an_undocumented_resolve_success_code_is_unavailable_not_not_found(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unknown ``success`` means "we could not ask", never "Steam said no".

    ``ResolveVanityURL`` is this module's only producer of ``not_found``, and
    ``not_found`` is the only verdict that hard-blocks a paying buyer, with no
    override in either UI. Steam documents exactly two values -- ``1``
    (resolved) and ``42`` ("No match") -- so anything else is an undocumented
    condition on Steam's side, which is the same class of event as a timeout
    or a 500: everywhere else this module already calls that ``unavailable``.
    Treating it as a definitive negative made the one blocking verdict rest on
    the weakest evidence in the file (2026-09-04 review round 1).
    """
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 15, "message": "???"}})
    )
    # No _SUMMARIES_URL mock armed: an unresolved vanity must not reach
    # GetPlayerSummaries either way.

    r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["steam_id"] is None


@respx.mock
async def test_an_undocumented_resolve_success_code_is_never_cached(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """...and being ``unavailable``, it must not be written to Redis.

    Caching it would keep repeating a transient Steam-side condition back at
    the next buyer for six hours.
    """
    _enable(monkeypatch)
    route = respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 15}})
    )

    await _check(integration_client, _VANITY_LINK)
    await _check(integration_client, _VANITY_LINK)

    assert route.call_count == 2


# ---------- the two link shapes never share a cache entry ----------
#
# `_STEAM_ID64_RE` is `\d{17}` and `_STEAM_VANITY_RE` is `[A-Za-z0-9_-]{2,32}`,
# so EVERY steamid64 is also a syntactically valid vanity name. One cache
# namespace for both meanings was a six-hour denial of purchase against any
# Steam account, reachable from a single unauthenticated request.


@respx.mock
async def test_a_not_found_vanity_never_answers_for_the_same_digits_as_a_steamid(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The attack, and the honest-mistake version of it.

    ``POST {"invite_url": "steamcommunity.com/id/{17 digits}"}`` resolves an
    unregistered vanity, so Steam answers the documented ``success == 42`` and
    we file ``not_found``. If that entry were keyed on the digits alone, the
    real buyer pasting ``/profiles/{same digits}`` would read it back, never
    reach ``GetPlayerSummaries``, and find Buy disabled with «Профиль Steam не
    найден» -- with no override on either surface, for six hours. The same
    thing happens with no attacker at all: a buyer who pastes a numeric id
    into the ``/id/`` form (a common confusion), sees «не найден», and
    corrects the link would stay blocked.
    """
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 42, "message": "No match"}})
    )
    summaries = respx.get(_SUMMARIES_URL).mock(
        return_value=httpx.Response(200, json=_summaries_payload())
    )

    poisoned = await _check(integration_client, f"https://steamcommunity.com/id/{_STEAM_ID}")
    assert poisoned.json()["status"] == "not_found"

    real = await _check(integration_client, _PROFILE_LINK)

    assert real.status_code == 200, real.text
    assert real.json()["status"] == "found"
    assert real.json()["steam_id"] == _STEAM_ID
    # The summaries call actually happened -- i.e. the vanity verdict was not
    # read back for the steamid64 shape.
    assert summaries.call_count == 1


@respx.mock
async def test_a_found_vanity_is_never_replayed_as_the_steamid_card(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction, which is worse for trust than a blocked sale.

    A vanity made of 17 digits that really is registered -- to somebody else
    entirely -- would otherwise have its avatar and nickname replayed as the
    confirmation card for ``/profiles/{same digits}``: a stranger presented as
    the buyer's recipient, one tap before an irreversible payment.
    """
    _enable(monkeypatch)
    other_id = "76561198000000999"
    respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 1, "steamid": other_id}})
    )
    summaries = respx.get(_SUMMARIES_URL)
    summaries.side_effect = [
        httpx.Response(200, json=_summaries_payload(name="someone-else")),
        httpx.Response(200, json=_summaries_payload(name="the-real-recipient")),
    ]

    vanity = await _check(integration_client, f"https://steamcommunity.com/id/{_STEAM_ID}")
    assert vanity.json()["status"] == "found"
    assert vanity.json()["steam_id"] == other_id
    assert vanity.json()["nickname"] == "someone-else"

    real = await _check(integration_client, _PROFILE_LINK)

    assert real.json()["status"] == "found"
    assert real.json()["steam_id"] == _STEAM_ID
    assert real.json()["nickname"] == "the-real-recipient"
    assert summaries.call_count == 2


# ---------- Steam's definitive "no such account" on the summaries call ------


@respx.mock
async def test_an_empty_players_array_on_a_profiles_link_is_not_found(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 with ``players: []`` is Steam saying no, and must read that way.

    ``/profiles/{steamid64}`` is the shape Steam's own "Copy profile URL"
    button hands to every user without a custom URL, so roughly half the links
    this endpoint sees never touch ``ResolveVanityURL`` at all. Before this,
    the summaries call's definitive negative was flattened into the same
    ``(None, None)`` a timeout produces, so a mistyped digit answered «Steam
    сейчас не отвечает — можно продолжить» and the buyer paid for a gift that
    went nowhere. That copy was not merely unhelpful, it was false.
    """
    _enable(monkeypatch)
    respx.get(_SUMMARIES_URL).mock(
        return_value=httpx.Response(200, json={"response": {"players": []}})
    )

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "not_found"
    assert body["steam_id"] is None
    assert body["nickname"] is None
    assert body["avatar_url"] is None


@respx.mock
async def test_a_not_found_from_an_empty_players_array_is_cached(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It is a fact about the profile, so it caches like any other one."""
    _enable(monkeypatch)
    summaries = respx.get(_SUMMARIES_URL).mock(
        return_value=httpx.Response(200, json={"response": {"players": []}})
    )

    await _check(integration_client, _PROFILE_LINK)
    second = await _check(integration_client, _PROFILE_LINK)

    assert second.json()["status"] == "not_found"
    assert summaries.call_count == 1


@respx.mock
async def test_an_empty_players_array_on_an_already_resolved_vanity_is_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `/profiles/` rule stops at the `/profiles/` shape, deliberately.

    On the vanity path a profile that does not exist is already answered one
    call earlier, by `ResolveVanityURL`'s documented `success == 42`. So the
    only inputs this branch could newly block are ones where Steam call #1
    said "this account exists, here is its steamid64" and call #2 said "no
    account holds that steamid64" -- a contradiction between two Steam
    services, never a clean negative. Zero true-positive upside, and a real
    downside: a buyer caught in a Steam eventual-consistency window would be
    hard-blocked with no override, on a verdict cached for six hours, so even
    re-pasting the correct link would not help.

    This is the module's own standing rule, not a shape-specific carve-out:
    `not_found` requires evidence nothing else contradicts -- the same
    reasoning that sends an undocumented `ResolveVanityURL` success code to
    `unavailable` rather than `not_found`.
    """
    _enable(monkeypatch)
    resolve = respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 1, "steamid": _STEAM_ID}})
    )
    summaries = respx.get(_SUMMARIES_URL).mock(
        return_value=httpx.Response(200, json={"response": {"players": []}})
    )

    r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unavailable"

    # And never cached, like every other `unavailable`: a second look asks
    # Steam again rather than replaying our own confusion for six hours.
    await _check(integration_client, _VANITY_LINK)
    assert resolve.call_count == 2
    assert summaries.call_count == 2


_DEGRADED_SUMMARIES_BODIES: list[Any] = [
    {},
    {"response": {}},
    {"response": {"players": None}},
    {"response": {"players": "nope"}},
    [],
    "not an object at all",
]


@respx.mock
@pytest.mark.parametrize("body", _DEGRADED_SUMMARIES_BODIES)
async def test_a_degraded_200_from_steam_is_unavailable_never_a_cached_not_found(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, body: Any
) -> None:
    """ "Absent" is not "empty", and only one of them is Steam saying no.

    `resp.json().get("response", {}).get("players", [])` read every one of
    these bodies as an empty player list -- a degraded ISteamUser response, or
    an intermediary returning a JSON error page under a 200 -- and turned it
    into `not_found`, written to Redis for six hours. Every buyer checking
    that recipient then saw «Профиль Steam не найден» with Buy disabled and no
    override, off one bad upstream response (2026-09-04 re-review). The shape
    is validated now and anything else raises `ValueError`, which lands on
    `unavailable` like every other Steam problem.

    The last two entries also close a hole that predates all of this: a
    non-dict body made `.get` raise `AttributeError`, which `fetch_persona`'s
    `except (httpx.HTTPError, ValueError)` never caught -- so the same
    response would have 500'd a Steam *login*, not just this check.
    """
    _enable(monkeypatch)
    summaries = respx.get(_SUMMARIES_URL).mock(return_value=httpx.Response(200, json=body))

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unavailable"

    # Not cached -- this is our (or Steam's) failure, not a fact about the
    # profile, and caching it is what made the bug six hours long.
    await _check(integration_client, _PROFILE_LINK)
    assert summaries.call_count == 2


@respx.mock
async def test_a_player_with_no_renderable_persona_is_still_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`found` still requires a persona -- restoring the negative must not
    regress the empty-confirmation-card fix. A player row that carries neither
    a name nor an avatar has confirmed nothing the buyer can act on, and is
    NOT Steam saying the account is absent, so it stays `unavailable` (and
    uncached)."""
    _enable(monkeypatch)
    summaries = respx.get(_SUMMARIES_URL).mock(
        return_value=httpx.Response(200, json={"response": {"players": [{"steamid": _STEAM_ID}]}})
    )

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.json()["status"] == "unavailable"
    # Never cached: a second call asks Steam again.
    await _check(integration_client, _PROFILE_LINK)
    assert summaries.call_count == 2


# ---------- s.team friend-invite links ----------


@respx.mock
async def test_s_team_link_is_unsupported_with_no_steam_call(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    # No respx mocks armed at all -- any outbound request fails the test.

    r = await _check(integration_client, _S_TEAM_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "unsupported"
    assert body["steam_id"] is None


# ---------- soft failures: never a blocking answer ----------


@respx.mock
async def test_missing_api_key_is_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch, api_key=None)
    # No mocks armed: an unset key must short-circuit before any Steam call.

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["steam_id"] is None


@respx.mock
async def test_steam_timeout_resolving_a_vanity_is_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A timeout during `ResolveVanityURL` means we never learned whether the
    vanity resolves at all -- the one Steam call whose failure genuinely
    must read as `unavailable`, not a guess either way."""
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(side_effect=httpx.ConnectTimeout("steam is slow"))

    r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["steam_id"] is None
    assert body["nickname"] is None


@respx.mock
async def test_resolve_vanity_transport_error_is_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(side_effect=httpx.ConnectError("steam is down"))

    r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unavailable"


@respx.mock
async def test_resolve_vanity_5xx_is_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(return_value=httpx.Response(500))

    r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unavailable"


# ---------- security: no secrets/PII in logs ----------


@respx.mock
async def test_resolve_vanity_5xx_never_leaks_the_api_key_into_logs(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`httpx.HTTPStatusError.__str__` embeds the full request URL, query
    string included -- and `_resolve_vanity` puts `STEAM_API_KEY` in that
    query string. Logging `str(exc)` verbatim would leak it, the same class
    of bug `core/logging.py` already flags for Waxpeer; this pins that the
    profile-check module never does that. `structlog.testing.capture_logs()`
    is the real-behaviour-verifying substitute for `caplog` in this codebase
    -- see `test_player_check_endpoint.py::test_player_id_never_logged_plaintext`
    for why `caplog` itself stays empty regardless of what is logged here."""
    secret_key = "super-secret-steam-key"
    _enable(monkeypatch, api_key=secret_key)
    respx.get(_RESOLVE_URL).mock(return_value=httpx.Response(500))

    with structlog.testing.capture_logs() as cap:
        r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unavailable"
    log_text = " ".join(repr(entry) for entry in cap)
    assert secret_key not in log_text


@respx.mock
async def test_a_summaries_timeout_on_a_profiles_link_is_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `/profiles/{steamid64}` link needs no *resolve* call, but its
    *existence* is still unverified: the id came straight from the URL,
    regex-shape-checked only. `GetPlayerSummaries` is the only existence
    check this shape gets, so a call that never landed cannot read as
    `found` -- unlike Steam sign-in, nothing has proven identity first. A
    Steam-side *answer* of `players: []` is a different thing entirely and
    reads as `not_found`; see the sibling above."""
    _enable(monkeypatch)
    summaries_route = respx.get(_SUMMARIES_URL)
    summaries_route.side_effect = [
        httpx.ConnectTimeout("steam is slow"),
        httpx.Response(200, json=_summaries_payload()),
    ]

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["steam_id"] is None
    assert body["nickname"] is None
    assert body["avatar_url"] is None

    # Nothing was written to the cache for that unavailable verdict -- the
    # same assertion its vanity-path sibling makes. Caching is gated on the
    # verdict alone, not the link shape, and this pins that: a regression
    # that reintroduced shape-dependent caching here would otherwise pass.
    second = await _check(integration_client, _PROFILE_LINK)
    assert second.json()["status"] == "found"
    assert summaries_route.call_count == 2


@respx.mock
async def test_a_summaries_timeout_on_a_resolved_vanity_is_also_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same rule, the other shape: `ResolveVanityURL` succeeding proves the
    account exists, but `found` is still withheld when `GetPlayerSummaries`
    never lands -- the deliverable is the avatar/nickname, not the bare fact
    of existence, so a verdict with neither must not become a green
    confirmation the buyer sees (and would otherwise sit cached for 6h)."""
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 1, "steamid": _STEAM_ID}})
    )
    summaries_route = respx.get(_SUMMARIES_URL)
    summaries_route.side_effect = [
        httpx.ConnectTimeout("steam is slow"),
        httpx.Response(200, json=_summaries_payload()),
    ]

    r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "unavailable"
    assert body["steam_id"] is None
    assert body["nickname"] is None
    assert body["avatar_url"] is None

    # Nothing was written to the cache for that unavailable verdict -- a
    # second call re-resolves and re-summarises rather than replaying it.
    second = await _check(integration_client, _VANITY_LINK)
    assert second.json()["status"] == "found"
    assert summaries_route.call_count == 2


# ---------- invalid link shapes ----------


async def test_a_link_checkout_would_reject_is_a_422(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same canonicalizer as checkout: a link neither endpoint accepts is a
    422, not a soft `unavailable`/`unsupported` verdict."""
    _enable(monkeypatch)

    r = await _check(integration_client, "https://evil.example/not-steam-at-all")

    assert r.status_code == 422, r.text


# ---------- the link never rides in a URL ----------


async def test_a_get_with_the_link_in_the_query_string_is_405(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The route is POST-only on purpose, and this is the test that keeps it
    that way.

    `api.yupay.uz`'s Caddy site block logs each request's `uri` verbatim,
    query string included, and promtail ships that to Loki -- so serving this
    check over GET would put `steamcommunity.com/id/{vanity}`, a *third
    party's* identity, into the logs, in a module that otherwise reduces the
    same identifier to `hash_short()` before logging it. A future
    convenience refactor back to GET has to delete this test to pass, which
    is exactly the amount of friction that decision deserves.
    """
    _enable(monkeypatch)

    r = await integration_client.get(
        "/api/v1/gifts/steam-profile", params={"invite_url": _PROFILE_LINK}
    )

    assert r.status_code == 405, r.text


# ---------- caching ----------


@respx.mock
async def test_a_second_identical_call_is_served_from_cache(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    route = respx.get(_SUMMARIES_URL).mock(
        return_value=httpx.Response(200, json=_summaries_payload())
    )

    first = await _check(integration_client, _PROFILE_LINK)
    second = await _check(integration_client, _PROFILE_LINK)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert route.call_count == 1


@respx.mock
async def test_not_found_vanity_verdict_is_also_cached(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    route = respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 42, "message": "No match"}})
    )

    first = await _check(integration_client, _VANITY_LINK)
    second = await _check(integration_client, _VANITY_LINK)

    assert first.json()["status"] == second.json()["status"] == "not_found"
    assert route.call_count == 1


@respx.mock
async def test_unavailable_verdict_is_never_cached(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cache-poisoned `unavailable` would keep telling the next buyer the
    same lie after Steam recovers -- so an outage must hit Steam again next
    time, unlike `found`/`not_found` above."""
    _enable(monkeypatch)
    route = respx.get(_RESOLVE_URL).mock(return_value=httpx.Response(500))

    first = await _check(integration_client, _VANITY_LINK)
    second = await _check(integration_client, _VANITY_LINK)

    assert first.json()["status"] == second.json()["status"] == "unavailable"
    assert route.call_count == 2


@respx.mock
async def test_a_malformed_cache_entry_never_500s(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`GiftProfileOut.model_validate_json` raises `pydantic.ValidationError`
    (a `ValueError` subclass) on a schema-mismatched blob and
    `json.JSONDecodeError` (also a `ValueError` subclass) on unparseable
    JSON -- neither is a `RedisError`. A stale/malformed value under this
    key (e.g. left behind by a future schema change) must degrade like a
    cache miss, never a 500, on an endpoint whose entire point is to never
    be the reason a request fails. No API key is configured, so a cache
    miss here would fall through to `unavailable` without any Steam call
    -- proving the bad entry was actually read and discarded, not merely
    never reached.

    The key is spelled out literally, `:sid:` namespace included, so that a
    change to the namespacing breaks this test loudly instead of quietly
    turning it into an assertion about a key nothing reads. The first half
    below is what makes that real: with no API key and no Steam mocks armed,
    only a cache hit can produce `found`."""
    _enable(monkeypatch, api_key=None)
    key = f"gifts:steam_profile:sid:{_STEAM_ID}"
    good = GiftProfileOut(
        status="found", steam_id=_STEAM_ID, nickname="jama", avatar_url=None
    ).model_dump_json()
    await get_redis().set(key, good)
    assert (await _check(integration_client, _PROFILE_LINK)).json()["status"] == "found"

    await get_redis().set(key, "not json and not a verdict")

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unavailable"


@respx.mock
async def test_the_total_steam_budget_degrades_to_unavailable_never_a_500(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deadline over both Steam calls answers, it does not blow up.

    `_TIMEOUT_SECONDS` is per-operation, so the vanity path's worst case ran
    past the 8 s both frontends allow before they abort — the buyer was told
    «Steam не отвечает» while this side went on to finish and cache a `found`
    nobody saw (2026-09-04 final review). `_TOTAL_BUDGET_SECONDS` caps the
    whole thing below that, and the `TimeoutError` it raises has to land on
    the same `unavailable` every other Steam problem does, never a 500 on an
    endpoint whose entire point is never to be the reason a request fails.
    """
    _enable(monkeypatch)
    monkeypatch.setattr(profile_mod, "_TOTAL_BUDGET_SECONDS", 0.05)

    async def _slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json=_summaries_payload())

    respx.get(_SUMMARIES_URL).mock(side_effect=_slow)

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unavailable"


@respx.mock
async def test_the_budget_spans_both_steam_calls_not_just_the_last_one(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vanity path is the whole reason the budget exists.

    Its two Steam calls are sequential and `_TIMEOUT_SECONDS` is
    per-operation, so a deadline wrapped around only the summaries call would
    leave exactly the regression this guards against -- and the one-call
    `/profiles/` test above would not notice (2026-09-04 re-review). Here each
    call comfortably beats its own share and only their *sum* blows the
    budget.
    """
    _enable(monkeypatch)
    monkeypatch.setattr(profile_mod, "_TOTAL_BUDGET_SECONDS", 0.3)

    async def _slow_resolve(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200, json={"response": {"success": 1, "steamid": _STEAM_ID}})

    async def _slow_summaries(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.2)
        return httpx.Response(200, json=_summaries_payload())

    respx.get(_RESOLVE_URL).mock(side_effect=_slow_resolve)
    respx.get(_SUMMARIES_URL).mock(side_effect=_slow_summaries)

    r = await _check(integration_client, _VANITY_LINK)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unavailable"


# ---------- rate limiting ----------


@respx.mock
async def test_the_endpoint_has_its_own_rate_limit_bucket(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`gifts-steam-profile` is a distinct `guard_ip` bucket -- pinned
    explicitly rather than counting on the shared default, same as
    `check_player`'s own bucket test (``test_player_check_endpoint.py``)."""
    _enable(monkeypatch)
    monkeypatch.setenv("AUTH_IP_GUARD_BUCKET_MAX", '{"gifts-steam-profile": 4}')
    cfg.get_settings.cache_clear()
    respx.get(_SUMMARIES_URL).mock(return_value=httpx.Response(200, json=_summaries_payload()))

    last = None
    for _ in range(8):
        last = await _check(integration_client, _PROFILE_LINK)
    assert last is not None
    assert last.status_code == 429, last.text
    # The trailing `cache_clear()` this test used to carry is now the
    # file-wide `_settings_cache_teardown` fixture -- the leak was never
    # unique to this test, every `_enable` had it.
