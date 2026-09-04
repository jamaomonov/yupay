"""`POST /gifts/steam-profile` has to be explicable after the fact.

The endpoint is unauthenticated, it is rate-limited per IP only, and every
distinct link it is handed costs one or two calls against a Steam Web API key
whose 100k/day ceiling **Steam sign-in shares**. It degrades safely — an
exhausted key makes checks read `unavailable` and sign-ins go nameless — but
before these counters existed nothing could answer "who burned the quota", or
even "how much of it is gone".

What is asserted here:

- every verdict the buyer can be shown moves
  `yupay_gifts_steam_profile_checks_total`, labelled with where the verdict
  came from (`steam` / `cache` / `local`);
- every keyed Steam call moves `yupay_steam_web_api_calls_total`, labelled by
  endpoint and by consumer — the label that makes the shared-key denominator
  addable across the gift check and sign-in;
- a Redis hit spends no quota, which is what makes a collapsing hit rate the
  early signal of someone walking distinct links;
- and a metrics registry that throws cannot change a verdict or fail a
  request. That last one is the point of the whole design: a counter is an
  observation about the work, never part of it.

Counters are process-global and other tests in the same worker increment them
too, so every assertion here is a **delta** taken around the call.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from httpx import AsyncClient
from prometheus_client import REGISTRY
from yupay.core import config as cfg
from yupay.core import metrics as metrics_mod

pytestmark = pytest.mark.asyncio

_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
_RESOLVE_URL = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"

_CHECKS = "yupay_gifts_steam_profile_checks_total"
_CALLS = "yupay_steam_web_api_calls_total"

_STEAM_ID = "76561198000000501"
_PROFILE_LINK = f"https://steamcommunity.com/profiles/{_STEAM_ID}"
_VANITY_LINK = "https://steamcommunity.com/id/metrics_vanity-01"
_S_TEAM_LINK = "https://s.team/p/metricsXY"


@pytest.fixture(autouse=True)
def _settings_cache_teardown():
    """Undo `_enable`'s `lru_cache` clear — see the sibling routes test file."""
    yield
    cfg.get_settings.cache_clear()


def _enable(monkeypatch: pytest.MonkeyPatch, *, api_key: str | None = "test-steam-key") -> None:
    monkeypatch.setenv("STEAM_GIFTS_ENABLED", "true")
    if api_key is None:
        monkeypatch.delenv("STEAM_API_KEY", raising=False)
    else:
        monkeypatch.setenv("STEAM_API_KEY", api_key)
    cfg.get_settings.cache_clear()


def _value(name: str, **labels: str) -> float:
    """One counter sample, or 0.0 before that label combination has been used."""
    return REGISTRY.get_sample_value(name, labels) or 0.0


def _summaries_payload() -> dict[str, Any]:
    return {"response": {"players": [{"personaname": "jama", "avatarfull": "https://cdn/a.jpg"}]}}


async def _check(client: AsyncClient, invite_url: str) -> httpx.Response:
    return await client.post("/api/v1/gifts/steam-profile", json={"invite_url": invite_url})


# ---------- the verdict counter moves, once, on the right label ----------


@respx.mock
async def test_a_found_verdict_is_counted_as_found_from_steam(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable(monkeypatch)
    respx.get(_SUMMARIES_URL).mock(return_value=httpx.Response(200, json=_summaries_payload()))
    before = _value(_CHECKS, verdict="found", source="steam")

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.json()["status"] == "found"
    assert _value(_CHECKS, verdict="found", source="steam") == before + 1


@respx.mock
async def test_a_not_found_verdict_is_counted_as_not_found_from_steam(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A `not_found` spike is either abuse or a broken client, and this is the
    only counter that can tell the two apart from the `found` baseline."""
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 42, "message": "No match"}})
    )
    before = _value(_CHECKS, verdict="not_found", source="steam")

    r = await _check(integration_client, _VANITY_LINK)

    assert r.json()["status"] == "not_found"
    assert _value(_CHECKS, verdict="not_found", source="steam") == before + 1


@respx.mock
async def test_an_unsupported_link_is_counted_as_local_and_spends_no_quota(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`s.team` friend tokens make no Steam call at all, so they are neither a
    cache hit nor a miss — counting them as either would make a flood of them
    read as a cache collapse."""
    _enable(monkeypatch)
    before = _value(_CHECKS, verdict="unsupported", source="local")
    calls_before = _total_calls()

    r = await _check(integration_client, _S_TEAM_LINK)

    assert r.json()["status"] == "unsupported"
    assert _value(_CHECKS, verdict="unsupported", source="local") == before + 1
    assert _total_calls() == calls_before


@respx.mock
async def test_a_steam_failure_is_counted_as_unavailable_from_steam(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An `unavailable` spike means Steam trouble (or an exhausted key), which
    is only legible next to the call-outcome counter — hence both here."""
    _enable(monkeypatch)
    respx.get(_SUMMARIES_URL).mock(return_value=httpx.Response(500))
    before = _value(_CHECKS, verdict="unavailable", source="steam")
    errors_before = _value(
        _CALLS, endpoint="get_player_summaries", consumer="gifts_profile", outcome="error"
    )

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.json()["status"] == "unavailable"
    assert _value(_CHECKS, verdict="unavailable", source="steam") == before + 1
    assert (
        _value(_CALLS, endpoint="get_player_summaries", consumer="gifts_profile", outcome="error")
        == errors_before + 1
    )


@respx.mock
async def test_a_malformed_200_body_is_counted_as_an_ok_call_but_an_unavailable_verdict(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`steam_web_api_call` wraps only the request and `raise_for_status()` —
    deliberately not the JSON parsing after it (see the context manager's own
    docstring, and `resolve_persona`'s). So a 200 whose *body* breaks Steam's
    own documented shape must still read as a successful call: the quota was
    spent either way, and it is `verdict`, not `outcome`, that has to say the
    answer was unusable.

    Distinct from `test_a_steam_failure_is_counted_as_unavailable_from_steam`
    above, which is a transport-level 500 — `outcome="error"`. Here the
    request succeeds and `raise_for_status()` passes; only the body fails.
    """
    _enable(monkeypatch)
    # `players` present but not a *list* — `resolve_persona` demands a real
    # list before it will treat this as Steam's "no such account" (2026-09-04
    # re-review, see its own docstring), so this degrades to a `ValueError`
    # raised *after* the call is already counted, not to `not_found`.
    respx.get(_SUMMARIES_URL).mock(
        return_value=httpx.Response(200, json={"response": {"players": "not-a-list"}})
    )
    ok_before = _value(
        _CALLS, endpoint="get_player_summaries", consumer="gifts_profile", outcome="ok"
    )
    verdicts_before = _value(_CHECKS, verdict="unavailable", source="steam")

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.json()["status"] == "unavailable"
    assert (
        _value(_CALLS, endpoint="get_player_summaries", consumer="gifts_profile", outcome="ok")
        == ok_before + 1
    ), "the request succeeded and raise_for_status() passed — this call is `ok`"
    assert _value(_CHECKS, verdict="unavailable", source="steam") == verdicts_before + 1


async def test_a_missing_api_key_is_counted_as_local_not_as_a_steam_failure(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both answer `unavailable` to the buyer, but only one of them is Steam's
    fault — and only one of them spent quota."""
    _enable(monkeypatch, api_key=None)
    before = _value(_CHECKS, verdict="unavailable", source="local")
    calls_before = _total_calls()

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.json()["status"] == "unavailable"
    assert _value(_CHECKS, verdict="unavailable", source="local") == before + 1
    assert _total_calls() == calls_before


# ---------- the quota counter ----------


def _total_calls() -> float:
    """Every keyed Steam call, across both endpoints and both consumers —
    the shared-key denominator the daily ceiling actually applies to."""
    total = 0.0
    for endpoint in ("resolve_vanity_url", "get_player_summaries"):
        for consumer in ("gifts_profile", "auth_signin"):
            for outcome in ("ok", "error"):
                total += _value(_CALLS, endpoint=endpoint, consumer=consumer, outcome=outcome)
    return total


@respx.mock
async def test_a_vanity_link_costs_two_calls_and_both_are_counted(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The vanity path resolves *then* summarises: one link, two units of
    quota. Counting the request instead of the calls would understate the
    burn by half on exactly the shape an abuser would pick."""
    _enable(monkeypatch)
    respx.get(_RESOLVE_URL).mock(
        return_value=httpx.Response(200, json={"response": {"success": 1, "steamid": _STEAM_ID}})
    )
    respx.get(_SUMMARIES_URL).mock(return_value=httpx.Response(200, json=_summaries_payload()))
    resolve_before = _value(
        _CALLS, endpoint="resolve_vanity_url", consumer="gifts_profile", outcome="ok"
    )
    summaries_before = _value(
        _CALLS, endpoint="get_player_summaries", consumer="gifts_profile", outcome="ok"
    )

    r = await _check(integration_client, _VANITY_LINK)

    assert r.json()["status"] == "found"
    assert (
        _value(_CALLS, endpoint="resolve_vanity_url", consumer="gifts_profile", outcome="ok")
        == resolve_before + 1
    )
    assert (
        _value(_CALLS, endpoint="get_player_summaries", consumer="gifts_profile", outcome="ok")
        == summaries_before + 1
    )


@respx.mock
async def test_a_cache_hit_is_counted_as_a_cache_hit_and_spends_no_quota(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cache effectiveness is the early warning: distinct links never hit, so
    a hit rate falling towards zero is someone walking the keyspace long
    before the quota graph looks alarming."""
    _enable(monkeypatch)
    respx.get(_SUMMARIES_URL).mock(return_value=httpx.Response(200, json=_summaries_payload()))
    await _check(integration_client, _PROFILE_LINK)

    hits_before = _value(_CHECKS, verdict="found", source="cache")
    calls_before = _total_calls()

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.json()["status"] == "found"
    assert _value(_CHECKS, verdict="found", source="cache") == hits_before + 1
    assert _total_calls() == calls_before, "a cache hit must not spend quota"


# ---------- and none of it may ever fail a request ----------


class _BrokenCounter:
    """A registry that throws on every increment, the way a duplicated
    registration or a label-name mismatch would."""

    def labels(self, **_: str) -> Any:
        raise RuntimeError("registry is broken")


@respx.mock
async def test_a_broken_metrics_registry_changes_no_verdict_and_fails_no_request(
    integration_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint's standing rule is that it must never be the reason a sale
    fails. Adding observability must not add a failure mode: with both
    counters throwing, the buyer still gets the same 200 and the same verdict.
    """
    _enable(monkeypatch)
    respx.get(_SUMMARIES_URL).mock(return_value=httpx.Response(200, json=_summaries_payload()))
    monkeypatch.setattr(metrics_mod, "GIFT_PROFILE_CHECKS", _BrokenCounter())
    monkeypatch.setattr(metrics_mod, "STEAM_WEB_API_CALLS", _BrokenCounter())

    r = await _check(integration_client, _PROFILE_LINK)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "found"
    assert body["steam_id"] == _STEAM_ID
    assert body["nickname"] == "jama"
