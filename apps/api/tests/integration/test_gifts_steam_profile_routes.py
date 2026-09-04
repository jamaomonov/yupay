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

from typing import Any

import httpx
import pytest
import respx
import structlog.testing
from httpx import AsyncClient
from yupay.core import config as cfg
from yupay.core.redis import get_redis

pytestmark = pytest.mark.asyncio

_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
_RESOLVE_URL = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"

_STEAM_ID = "76561198000000123"
_PROFILE_LINK = f"https://steamcommunity.com/profiles/{_STEAM_ID}"
_VANITY_LINK = "https://steamcommunity.com/id/my_vanity-01"
_S_TEAM_LINK = "https://s.team/p/abcXYZ"


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
async def test_persona_fetch_failure_on_a_profiles_link_is_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `/profiles/{steamid64}` link needs no *resolve* call, but its
    *existence* is still unverified: the id came straight from the URL,
    regex-shape-checked only. `GetPlayerSummaries` is the only existence
    check this shape gets, so an empty answer -- Steam being down, or a
    genuinely nonexistent id, indistinguishable from here -- must not read
    as `found`. Unlike Steam sign-in, nothing has proven identity first."""
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
async def test_persona_fetch_failure_on_a_resolved_vanity_is_also_unavailable(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same rule, the other shape: `ResolveVanityURL` succeeding proves the
    account exists, but `found` is still withheld when `GetPlayerSummaries`
    comes back empty -- the deliverable is the avatar/nickname, not the bare
    fact of existence, so a verdict with neither must not become a green
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
    same identifier to `_hash_short()` before logging it. A future
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
    never reached."""
    _enable(monkeypatch, api_key=None)
    await get_redis().set(f"gifts:steam_profile:{_STEAM_ID}", "not json and not a verdict")

    r = await _check(integration_client, _PROFILE_LINK)

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
