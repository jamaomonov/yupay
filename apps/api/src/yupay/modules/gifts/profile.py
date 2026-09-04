"""Pre-purchase recipient check: who does a Steam link actually point to?

Before paying, the buyer presses «Проверить» next to the Steam profile link
they pasted in and sees the recipient's avatar and nickname — so a mistyped
link stops being an unrecoverable, paid mistake. This is server-side only:
Steam sends no CORS headers for our origin, so a browser can issue the
request but never read the response back.

**The one rule that matters:** this check must never be the reason a sale
fails when the failure is ours. :class:`~yupay.modules.gifts.schemas.
GiftProfileOut` has exactly four statuses, and only ``"not_found"`` — Steam
itself saying a profile does not exist — is allowed to read as a blocking
answer. An unset API key, a Steam outage, a timeout, an unparseable
response, or a link type the Web API cannot resolve at all (``s.team``
friend-invite tokens) all come back as ``"unavailable"``/``"unsupported"``,
which the frontend treats the same as "carry on".

Link parsing is delegated entirely to
:func:`yupay.modules.gifts.checkout.parse_invite_url` — the same
canonicalizer checkout itself calls — so a link this module accepts can
never be rejected at checkout, and vice versa.

Resolution, per canonical link shape:

- ``steamcommunity.com/profiles/{steamid64}`` — the id is already in the
  URL. No resolve call, and (deliberately) no existence check either: unlike
  a vanity name, there is no cheap Steam endpoint that answers "does this
  id exist" other than ``GetPlayerSummaries`` itself, which is best-effort
  and degrades on *any* failure (see :func:`~yupay.modules.auth.steam.
  fetch_persona`). Treating that degradation as ``"not_found"`` would make
  a transient Steam hiccup block a sale, which is exactly what this module
  exists to prevent — so this shape is always ``"found"``, with nickname
  and avatar filled in on a best-effort basis.
- ``steamcommunity.com/id/{vanity}`` — resolved via
  ``ISteamUser/ResolveVanityURL/v1/``. This is the one Steam call in the
  whole flow allowed to answer definitively: ``success != 1`` becomes
  ``"not_found"``, everything else about that call failing becomes
  ``"unavailable"``.
- ``s.team/p/{path}`` — a friend-invite token, not a profile. The Web API
  cannot resolve these at all, so this is ``"unsupported"`` with no Steam
  call made, ever.

Redis caches ``"found"``/``"not_found"`` verdicts for 6h under
``gifts:steam_profile:{steamid_or_vanity}`` (see
``docs/architecture/cache-keys.md``) — profiles change rarely.
``"unavailable"`` is never cached: it is our failure, not a fact about the
profile, and caching it would keep telling the next buyer the same lie.

PII note: ``steam_id``/nickname/avatar never appear in a log call here —
only an opaque hash of the link's own identifier, the same convention
``integrations.player_check`` uses for ``player_id``.
"""

from __future__ import annotations

import contextlib

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.core.redis import get_redis
from yupay.modules.auth.steam import fetch_persona
from yupay.modules.fulfillment.suppliers.g2b import _hash_short
from yupay.modules.gifts.checkout import parse_invite_url
from yupay.modules.gifts.schemas import GiftProfileOut

log = get_logger("yupay.gifts.profile")

_RESOLVE_VANITY_URL = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
_TIMEOUT_SECONDS = 5.0
_CACHE_TTL_SECONDS = 6 * 3600

_PROFILE_PREFIX = "https://steamcommunity.com/profiles/"
_VANITY_PREFIX = "https://steamcommunity.com/id/"
_S_TEAM_PREFIX = "https://s.team/"

_UNAVAILABLE = GiftProfileOut(status="unavailable", steam_id=None, nickname=None, avatar_url=None)
_UNSUPPORTED = GiftProfileOut(status="unsupported", steam_id=None, nickname=None, avatar_url=None)
_NOT_FOUND = GiftProfileOut(status="not_found", steam_id=None, nickname=None, avatar_url=None)


async def _resolve_vanity(vanity: str, *, api_key: str, http: httpx.AsyncClient) -> str | None:
    """Resolve a vanity name to a steamid64 via ``ISteamUser/ResolveVanityURL/v1/``.

    Args:
        vanity: the ``{vanity}`` path segment from a canonical
            ``steamcommunity.com/id/{vanity}`` link.
        api_key: our Steam Web API key.
        http: the client to issue the request on.

    Returns:
        The resolved steamid64, or ``None`` on Steam's own definitive
        ``success != 1`` "no such profile" answer — the single signal in
        this whole module allowed to become ``status="not_found"``.

    Raises:
        httpx.HTTPError: transport failure or a non-2xx response.
        ValueError: the response body was 200 but not shaped like a
            ``ResolveVanityURL`` answer (e.g. ``success == 1`` with no
            ``steamid``). The caller folds every one of these into
            ``"unavailable"`` — they mean "we could not ask", never "we
            asked and Steam said no".
    """
    resp = await http.get(_RESOLVE_VANITY_URL, params={"key": api_key, "vanityurl": vanity})
    resp.raise_for_status()
    body = resp.json().get("response", {})
    if body.get("success") == 1:
        steamid = body.get("steamid")
        if isinstance(steamid, str) and steamid:
            return steamid
        raise ValueError("ResolveVanityURL reported success without a steamid")
    return None


async def _cache_verdict(redis: Redis, key: str, out: GiftProfileOut) -> None:
    """Best-effort write of a ``found``/``not_found`` verdict. Never ``unavailable``.

    Redis errors are swallowed the same way every other cache write in this
    module (and ``gifts.service``) is: a cache miss on the next call is a
    fine outcome, a 500 on this advisory check is not.
    """
    with contextlib.suppress(RedisError):
        await redis.set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)


async def check_steam_profile(
    invite_url: str, *, http: httpx.AsyncClient | None = None
) -> GiftProfileOut:
    """Resolve a recipient's Steam link into the pre-purchase check's verdict.

    Never raises on a Steam-side problem — everything from an unset API key
    through a timeout to a malformed response degrades to
    ``status="unavailable"``. It *does* propagate
    :class:`~yupay.core.errors.ValidationError` from ``parse_invite_url``
    for a link that is not one of checkout's three accepted shapes at all;
    that is a client input error (422), not a Steam problem, and checkout
    would reject the exact same link for the exact same reason.

    Args:
        invite_url: the raw ``invite_url`` query value, any of the shapes
            :func:`~yupay.modules.gifts.checkout.parse_invite_url` accepts.
        http: injected client for tests; a real call builds and closes its
            own short-timeout client.

    Returns:
        The verdict. ``steam_id``/``nickname``/``avatar_url`` are populated
        only when ``status == "found"``.

    Raises:
        ValidationError: ``invite_url`` is not a Steam profile or friend
            link checkout would accept either.
    """
    canonical = parse_invite_url(invite_url)

    if canonical.startswith(_S_TEAM_PREFIX):
        # Friend-invite tokens are not profiles; the Web API has nothing that
        # resolves them. This is a fact about the link shape, not the
        # profile, so it's cheap enough to just say every time -- no Steam
        # call, no cache.
        return _UNSUPPORTED

    is_vanity = canonical.startswith(_VANITY_PREFIX)
    identifier = canonical.removeprefix(_VANITY_PREFIX if is_vanity else _PROFILE_PREFIX)

    cache_key = f"gifts:steam_profile:{identifier}"
    redis = get_redis()
    with contextlib.suppress(RedisError):
        cached = await redis.get(cache_key)
        if cached is not None:
            return GiftProfileOut.model_validate_json(cached)

    api_key = get_settings().steam_api_key
    if not api_key:
        return _UNAVAILABLE

    client = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    try:
        if is_vanity:
            resolved = await _resolve_vanity(identifier, api_key=api_key, http=client)
            if resolved is None:
                await _cache_verdict(redis, cache_key, _NOT_FOUND)
                return _NOT_FOUND
            steam_id = resolved
        else:
            steam_id = identifier
        nickname, avatar_url = await fetch_persona(int(steam_id), api_key=api_key, http=client)
    except Exception as exc:  # noqa: BLE001 -- a Steam problem is `unavailable`, never a 500
        log.warning(
            "gifts.steam_profile_unavailable",
            identifier_hash=_hash_short(identifier),
            error=str(exc)[:200],
        )
        return _UNAVAILABLE
    finally:
        if http is None:
            await client.aclose()

    out = GiftProfileOut(status="found", steam_id=steam_id, nickname=nickname, avatar_url=avatar_url)
    await _cache_verdict(redis, cache_key, out)
    log.info(
        "gifts.steam_profile_checked",
        identifier_hash=_hash_short(identifier),
        status=out.status,
    )
    return out


__all__ = ["check_steam_profile"]
