"""Steam sign-in: the assertion is only as good as Steam's own yes.

Pinned here: verification round-trips to Steam (a locally well-formed
callback with ``is_valid:false`` opens nothing), a ``return_to`` minted for
another site is refused before any network call, and the steamid becomes a
``steam_links`` account exactly once however many times it signs in.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from yupay.core.errors import UnauthorizedError
from yupay.modules.auth.service import steam_login
from yupay.modules.auth.steam import SteamAuthError, build_login_url, verify_callback
from yupay.modules.users.models import SteamLink

pytestmark = pytest.mark.asyncio

_OPENID = "https://steamcommunity.com/openid/login"


def _params(steam_id: str = "76561198000000001") -> dict[str, str]:
    return {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "id_res",
        "openid.claimed_id": f"https://steamcommunity.com/openid/id/{steam_id}",
        "openid.return_to": "https://yupay.uz/auth/steam/callback?locale=ru",
        "openid.sig": "sig",
        "openid.signed": "signed,fields",
    }


def test_login_url_carries_realm_and_return() -> None:
    url = build_login_url(
        return_to="https://yupay.uz/auth/steam/callback", realm="https://yupay.uz"
    )
    assert url.startswith(_OPENID)
    assert "checkid_setup" in url
    assert "yupay.uz" in url


@respx.mock
async def test_verify_round_trips_to_steam_and_returns_the_id() -> None:
    route = respx.post(_OPENID).mock(
        return_value=httpx.Response(
            200, text="ns:http://specs.openid.net/auth/2.0\nis_valid:true\n"
        )
    )
    steam_id = await verify_callback(
        _params(), expected_return_prefix="https://yupay.uz/auth/steam/callback"
    )
    assert steam_id == 76561198000000001
    sent = dict(httpx.QueryParams(route.calls[0].request.content.decode()))
    assert sent["openid.mode"] == "check_authentication"


@respx.mock
async def test_steam_saying_no_is_the_end_of_it() -> None:
    respx.post(_OPENID).mock(return_value=httpx.Response(200, text="is_valid:false\n"))
    with pytest.raises(SteamAuthError):
        await verify_callback(
            _params(), expected_return_prefix="https://yupay.uz/auth/steam/callback"
        )


async def test_a_foreign_return_to_never_reaches_steam() -> None:
    params = _params()
    params["openid.return_to"] = "https://evil.example/steal"
    with pytest.raises(SteamAuthError):
        # No respx mock armed: a network call here would error differently,
        # proving the refusal happens before any traffic.
        await verify_callback(params, expected_return_prefix="https://yupay.uz/auth/steam/callback")


async def test_steam_login_creates_one_account_and_reuses_it(
    db_session: AsyncSession,
) -> None:
    async def verify(params: dict[str, str], **_: object) -> int:
        return 76561198000000042

    first = await steam_login(db_session, _params(), verifier=verify)
    second = await steam_login(db_session, _params(), verifier=verify)
    assert first.access_token
    assert second.access_token

    links = (
        await db_session.execute(select(SteamLink).where(SteamLink.steam_id == 76561198000000042))
    ).all()
    assert len(links) == 1


async def test_a_rejected_assertion_is_a_401(db_session: AsyncSession) -> None:
    async def verify(params: dict[str, str], **_: object) -> int:
        raise SteamAuthError("nope")

    with pytest.raises(UnauthorizedError):
        await steam_login(db_session, _params(), verifier=verify)


@respx.mock
async def test_persona_fetch_failure_never_breaks_the_login(
    db_session: AsyncSession,
) -> None:
    from yupay.core.config import get_settings

    respx.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/").mock(
        return_value=httpx.Response(500)
    )
    s = get_settings().model_copy(update={"steam_api_key": "k"})

    async def verify(params: dict[str, str], **_: object) -> int:
        return 76561198000000077

    tokens = await steam_login(db_session, _params(), settings=s, verifier=verify)
    assert tokens.access_token
    link = (
        await db_session.execute(select(SteamLink).where(SteamLink.steam_id == 76561198000000077))
    ).scalar_one()
    assert link.persona_name is None  # nameless, not broken


@respx.mock
async def test_an_empty_players_array_still_logs_the_user_in_nameless(
    db_session: AsyncSession,
) -> None:
    """`fetch_persona` keeps folding "no such account" in with the failures.

    `resolve_persona` was added so the gift profile check can tell Steam's
    definitive negative apart from a call that never landed (2026-09-04 final
    review) -- but sign-in must not gain that distinction. OpenID has already
    proven this account exists by the time the summary call runs, so an empty
    `players` here is a Steam oddity, not grounds to refuse a login.
    """
    from yupay.core.config import get_settings

    respx.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/").mock(
        return_value=httpx.Response(200, json={"response": {"players": []}})
    )
    s = get_settings().model_copy(update={"steam_api_key": "k"})

    async def verify(params: dict[str, str], **_: object) -> int:
        return 76561198000000078

    tokens = await steam_login(db_session, _params(), settings=s, verifier=verify)
    assert tokens.access_token
    link = (
        await db_session.execute(select(SteamLink).where(SteamLink.steam_id == 76561198000000078))
    ).scalar_one()
    assert link.persona_name is None  # nameless, not broken


@respx.mock
@pytest.mark.parametrize(
    "body",
    [
        {},
        {"response": {}},
        {"response": {"players": None}},
        [],
        "not an object at all",
        # A well-formed `players` list whose first entry is not an object --
        # the same hole one nesting level down, found by the ship-gate review.
        {"response": {"players": [None]}},
        {"response": {"players": ["not an object"]}},
    ],
)
async def test_a_degraded_summaries_body_still_logs_the_user_in_nameless(
    db_session: AsyncSession, body: object
) -> None:
    """Sign-in survives a Steam response that is 200 but shaped wrong.

    `resolve_persona` now raises `ValueError` on a body with no
    `response.players` list rather than reading it as an empty one
    (2026-09-04 re-review) -- deliberately `ValueError`, because that is what
    `fetch_persona` already catches, so this call site is unchanged.

    The last two cases also close a hole that predates the gift check: a
    non-dict body made `.get` raise `AttributeError`, which is neither
    `httpx.HTTPError` nor `ValueError`, so it escaped that catch and 500'd
    the login outright.
    """
    from yupay.core.config import get_settings

    respx.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/").mock(
        return_value=httpx.Response(200, json=body)
    )
    s = get_settings().model_copy(update={"steam_api_key": "k"})
    steam_id = 76561198000000079

    async def verify(params: dict[str, str], **_: object) -> int:
        return steam_id

    tokens = await steam_login(db_session, _params(), settings=s, verifier=verify)
    assert tokens.access_token
    link = (
        await db_session.execute(select(SteamLink).where(SteamLink.steam_id == steam_id))
    ).scalar_one()
    assert link.persona_name is None  # nameless, not broken


@respx.mock
async def test_persona_and_avatar_land_on_the_profile(db_session: AsyncSession) -> None:
    from yupay.core.config import get_settings

    respx.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/").mock(
        return_value=httpx.Response(
            200,
            json={
                "response": {
                    "players": [
                        {
                            "personaname": "jama",
                            "avatarfull": "https://avatars.steamstatic.com/x_full.jpg",
                        }
                    ]
                }
            },
        )
    )
    s = get_settings().model_copy(update={"steam_api_key": "k"})

    async def verify(params: dict[str, str], **_: object) -> int:
        return 76561198000000088

    await steam_login(db_session, _params(), settings=s, verifier=verify)
    link = (
        await db_session.execute(select(SteamLink).where(SteamLink.steam_id == 76561198000000088))
    ).scalar_one()
    assert link.persona_name == "jama"
    assert link.user.display_name == "jama"
    assert link.user.photo_url == "https://avatars.steamstatic.com/x_full.jpg"


@respx.mock
async def test_a_sign_in_counts_against_the_same_shared_steam_quota(
    db_session: AsyncSession,
) -> None:
    """Sign-in and the gift recipient check spend ONE Steam Web API key.

    The key's 100k/day ceiling is shared, so a quota graph that counted only
    `gifts_profile` would understate the burn and mis-attribute the cause —
    a login storm would look like the gift check was fine while the key ran
    out from under it. `consumer` is what makes the two addable, and this is
    the half of that sum the gift tests cannot see.

    OpenID's own `check_authentication` round trip is deliberately *not*
    counted: it carries no API key and costs no quota.
    """
    from prometheus_client import REGISTRY
    from yupay.core.config import get_settings

    def calls() -> float:
        return (
            REGISTRY.get_sample_value(
                "yupay_steam_web_api_calls_total",
                {
                    "endpoint": "get_player_summaries",
                    "consumer": "auth_signin",
                    "outcome": "ok",
                },
            )
            or 0.0
        )

    respx.get("https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/").mock(
        return_value=httpx.Response(200, json={"response": {"players": [{"personaname": "j"}]}})
    )
    s = get_settings().model_copy(update={"steam_api_key": "k"})

    async def verify(params: dict[str, str], **_: object) -> int:
        return 76561198000000099

    before = calls()
    await steam_login(db_session, _params(), settings=s, verifier=verify)
    assert calls() == before + 1
