"""HTTP tests for the pre-purchase Steam profile check (`GET /gifts/steam-profile`).

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

`@respx.mock` blocks any unmocked outbound request by raising, which is what
makes "makes no resolve call" / "no Steam call at all" real assertions rather
than just an absence of a positive check.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient
from yupay.core import config as cfg

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
    return await client.get("/api/v1/gifts/steam-profile", params={"invite_url": invite_url})


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
        return_value=httpx.Response(
            200, json={"response": {"success": 42, "message": "No match"}}
        )
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


@respx.mock
async def test_persona_fetch_failure_on_a_profiles_link_still_reads_found(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `/profiles/{steamid64}` link needs no resolve call -- the id is
    already known from the URL, so its existence is never in question here.
    `GetPlayerSummaries` failing only costs the cosmetic nickname/avatar,
    exactly the same "nameless, not broken" degrade `fetch_persona` already
    gives Steam sign-in (`auth/steam.py`) -- it must never demote a
    known-shape link to a blocking verdict."""
    _enable(monkeypatch)
    respx.get(_SUMMARIES_URL).mock(side_effect=httpx.ConnectTimeout("steam is slow"))

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "found"
    assert body["steam_id"] == _STEAM_ID
    assert body["nickname"] is None
    assert body["avatar_url"] is None


# ---------- invalid link shapes ----------


async def test_a_link_checkout_would_reject_is_a_422(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same canonicalizer as checkout: a link neither endpoint accepts is a
    422, not a soft `unavailable`/`unsupported` verdict."""
    _enable(monkeypatch)

    r = await _check(integration_client, "https://evil.example/not-steam-at-all")

    assert r.status_code == 422, r.text


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
        return_value=httpx.Response(
            200, json={"response": {"success": 42, "message": "No match"}}
        )
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
