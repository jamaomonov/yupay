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

from yupay.core.metrics import SteamApiConsumer, steam_web_api_call

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


async def resolve_persona(
    steam_id: int,
    *,
    api_key: str,
    consumer: SteamApiConsumer,
    http: httpx.AsyncClient | None = None,
) -> tuple[str | None, str | None] | None:
    """``GetPlayerSummaries`` with Steam's "no such account" kept distinguishable.

    ``fetch_persona`` below flattens every outcome into ``(None, None)``,
    which is right for Steam sign-in and wrong for the pre-purchase recipient
    check: a 200 carrying ``players: []`` is Steam *answering* that no account
    holds this steamid64, and that is the only existence check a
    ``steamcommunity.com/profiles/{steamid64}`` link ever gets — the shape
    Steam's own "Copy profile URL" hands to every user without a custom URL.
    Collapsing it into the timeout case told those buyers «Steam сейчас не
    отвечает — можно продолжить» for a profile that does not exist, and they
    paid for a gift that went nowhere (2026-09-04 final review).

    Args:
        steam_id: the 64-bit Steam id to summarise.
        api_key: our Steam Web API key.
        consumer: which feature is spending the quota, for
            ``yupay_steam_web_api_calls_total``. Required rather than
            defaulted: the key's 100k/day ceiling is shared, so the only
            thing that makes a burn attributable is that every call site
            names itself, and a default would let a new one hide inside
            another's number.
        http: injected client for tests; otherwise one is built and closed
            here.

    Returns:
        ``None`` when Steam answered with an empty ``players`` array — its
        definitive "no account with this id". Otherwise the
        ``(persona_name, avatar_url)`` pair, either half of which may still
        be ``None`` when the player row carries no usable value; a pair of
        ``None``s means "Steam has this account but gave us nothing to
        render", which is *not* the same as the account being absent.

    Raises:
        httpx.HTTPError: transport failure, timeout, or a non-2xx response.
        ValueError: a 200 whose body was not JSON, or not the expected shape
            — including a body with no ``response.players`` *list* at all,
            which is a degraded answer rather than an empty one and must not
            be mistaken for Steam's "no such account".
    """
    client = http or httpx.AsyncClient(timeout=5.0)
    try:
        # The context manager counts the call itself -- the unit the daily
        # quota is charged in -- and nothing beyond it: the parsing below is
        # about the answer, and a 200 we could not read still spent quota.
        with steam_web_api_call(endpoint="get_player_summaries", consumer=consumer):
            resp = await client.get(_SUMMARIES, params={"key": api_key, "steamids": str(steam_id)})
            resp.raise_for_status()
        # "Absent" is not "empty", and only one of them is Steam saying no.
        # `resp.json().get("response", {}).get("players", [])` read a degraded
        # ISteamUser response -- `{}`, `{"response": {}}`, a `null` players, or
        # an intermediary's JSON error page under a 200 -- as an empty player
        # list, which the gift profile check then filed as a *blocking*
        # `not_found`, cached for six hours (2026-09-04 re-review). Only a
        # `players` list that is really there and really empty may mean that.
        # The `isinstance` on the body itself also closes an older hole: a
        # non-dict body made `.get` raise `AttributeError`, which is neither
        # `httpx.HTTPError` nor `ValueError`, so it escaped `fetch_persona`'s
        # catch and would have 500'd a Steam *login*.
        body = resp.json()
        response = body.get("response") if isinstance(body, dict) else None
        if not isinstance(response, dict) or not isinstance(response.get("players"), list):
            # The suppression below is deliberate: TRY004 wants `TypeError`
            # for an isinstance guard, but this is an upstream body breaking
            # its contract, not a Python type error -- and `TypeError` is
            # neither `httpx.HTTPError` nor `ValueError`, so it would escape
            # `fetch_persona`'s catch below and 500 a Steam login, which is
            # the exact hole this check exists to close.
            raise ValueError("GetPlayerSummaries returned an unexpected shape")  # noqa: TRY004
        players = response["players"]
        if not players:
            return None
        player = players[0]
        if not isinstance(player, dict):
            # Same contract break one nesting level down: a `players` list
            # that is really a list but whose first entry is not an object.
            # Without this, `.get` below raises `AttributeError`, which
            # escapes `fetch_persona`'s catch exactly like a non-dict body
            # would have -- so the guard above closed only two thirds of the
            # hole it claimed (2026-09-04 ship-gate review).
            raise ValueError("GetPlayerSummaries returned a non-object player")  # noqa: TRY004
        name = player.get("personaname")
        avatar = player.get("avatarfull") or player.get("avatarmedium")
        return (
            name if isinstance(name, str) and name else None,
            avatar if isinstance(avatar, str) and avatar else None,
        )
    finally:
        if http is None:
            await client.aclose()


async def fetch_persona(
    steam_id: int,
    *,
    api_key: str,
    http: httpx.AsyncClient | None = None,
) -> tuple[str | None, str | None]:
    """The persona name and avatar for a steamid, best-effort.

    OpenID proves the identity but carries no profile, so this is the only
    source for «покажи никнейм». Strictly cosmetic: any failure returns
    ``(None, None)`` and the login proceeds nameless rather than broken —
    and "no such account" is folded in with the failures on purpose, because
    by the time this runs OpenID has already proven the account exists.
    Callers that must tell those two apart use :func:`resolve_persona`.

    Its Steam call is counted under ``consumer="auth_signin"`` without asking
    the caller, because this function's contract *is* the sign-in one: "no
    such account" is folded in with the failures precisely because OpenID has
    already proven the account exists. A caller that is not a sign-in wants
    :func:`resolve_persona` and its explicit ``consumer``, or the quota
    numbers start lying about who spent what.
    """
    try:
        found = await resolve_persona(steam_id, api_key=api_key, consumer="auth_signin", http=http)
    except (httpx.HTTPError, ValueError):
        return None, None
    return found if found is not None else (None, None)


__all__ = [
    "SteamAuthError",
    "build_login_url",
    "fetch_persona",
    "resolve_persona",
    "verify_callback",
]
