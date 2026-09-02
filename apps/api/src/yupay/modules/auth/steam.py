"""Steam sign-in: OpenID 2.0, the only door Steam offers.

Steam never adopted OAuth: the browser is sent to
``steamcommunity.com/openid/login`` and comes back with a signed parameter
set. The ONLY trustworthy verification is handing that exact set back to
Steam with ``openid.mode=check_authentication`` — Steam answers
``is_valid:true`` once and marks the assertion used, which is also what
makes replays die at Steam's side rather than ours.

An external HTTP call on a request path is normally banned (§10); this one
is the documented exception: it IS the authentication, it happens once per
login on a low-rate credential endpoint behind ``ip_guard``, and it is
bounded by a short timeout.

No email comes back — only a steamid64 parsed from ``claimed_id`` — so a
Steam account is linked/created through ``steam_links`` exactly the way
Telegram accounts are.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

import httpx

_STEAM_OPENID = "https://steamcommunity.com/openid/login"
_CLAIMED_ID = re.compile(r"^https://steamcommunity\.com/openid/id/(\d{10,20})$")
_TIMEOUT_SECONDS = 10.0


class SteamAuthError(Exception):
    """The callback failed verification. Message is for logs, not clients."""


def build_login_url(*, return_to: str, realm: str) -> str:
    """The steamcommunity URL the browser is sent to.

    ``realm`` is what Steam shows the user as the requesting site and what
    the assertion is scoped to; ``return_to`` must live under it.
    """
    params = {
        "openid.ns": "http://specs.openid.net/auth/2.0",
        "openid.mode": "checkid_setup",
        "openid.return_to": return_to,
        "openid.realm": realm,
        "openid.identity": "http://specs.openid.net/auth/2.0/identifier_select",
        "openid.claimed_id": "http://specs.openid.net/auth/2.0/identifier_select",
    }
    return f"{_STEAM_OPENID}?{urlencode(params)}"


async def verify_callback(
    params: dict[str, str],
    *,
    expected_return_prefix: str,
    http: httpx.AsyncClient | None = None,
) -> int:
    """Verify a Steam OpenID callback and return the steamid64.

    Args:
        params: The ``openid.*`` query parameters exactly as Steam sent them.
        expected_return_prefix: Our own callback URL; a ``return_to`` pointing
            anywhere else means the assertion was minted for another site.
        http: Injected client for tests.

    Raises:
        SteamAuthError: Missing fields, foreign ``return_to``, Steam saying
            the assertion is not valid, or an unparseable ``claimed_id``.
    """
    claimed = params.get("openid.claimed_id", "")
    match = _CLAIMED_ID.match(claimed)
    if match is None:
        raise SteamAuthError("claimed_id is not a steam identity")
    return_to = params.get("openid.return_to", "")
    if not return_to.startswith(expected_return_prefix):
        raise SteamAuthError("return_to does not belong to us")

    check = {k: v for k, v in params.items() if k.startswith("openid.")}
    check["openid.mode"] = "check_authentication"

    client = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    try:
        resp = await client.post(
            _STEAM_OPENID,
            data=check,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.text
    except httpx.HTTPError as exc:
        raise SteamAuthError(f"steam unreachable: {exc}") from exc
    finally:
        if http is None:
            await client.aclose()

    if "is_valid:true" not in body:
        raise SteamAuthError("steam rejected the assertion")
    return int(match.group(1))


_SUMMARIES = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"


async def fetch_persona(
    steam_id: int,
    *,
    api_key: str,
    http: httpx.AsyncClient | None = None,
) -> tuple[str | None, str | None]:
    """The persona name and avatar for a steamid, best-effort.

    OpenID proves the identity but carries no profile, so this is the only
    source for «покажи никнейм». Strictly cosmetic: any failure returns
    ``(None, None)`` and the login proceeds nameless rather than broken.
    """
    client = http or httpx.AsyncClient(timeout=5.0)
    try:
        resp = await client.get(_SUMMARIES, params={"key": api_key, "steamids": str(steam_id)})
        resp.raise_for_status()
        players = resp.json().get("response", {}).get("players", [])
        if not players:
            return None, None
        player = players[0]
        name = player.get("personaname")
        avatar = player.get("avatarfull") or player.get("avatarmedium")
        return (
            name if isinstance(name, str) and name else None,
            avatar if isinstance(avatar, str) and avatar else None,
        )
    except (httpx.HTTPError, ValueError):
        return None, None
    finally:
        if http is None:
            await client.aclose()


__all__ = [
    "SteamAuthError",
    "build_login_url",
    "fetch_persona",
    "verify_callback",
]
