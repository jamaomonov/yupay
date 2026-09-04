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
  URL, so there is no *resolve* call. Its existence is still unverified at
  that point, though: ``_STEAM_ID64_RE`` in ``checkout.py`` only checks
  that it is 17 digits, not that such an account has ever existed.
- ``steamcommunity.com/id/{vanity}`` — resolved via
  ``ISteamUser/ResolveVanityURL/v1/``. This is the one Steam call in the
  whole flow allowed to answer definitively that a link does *not* exist:
  ``success != 1`` becomes ``"not_found"``; anything else about that call
  failing becomes ``"unavailable"``.
- ``s.team/p/{path}`` — a friend-invite token, not a profile. The Web API
  cannot resolve these at all, so this is ``"unsupported"`` with no Steam
  call made, ever.

Both of the first two shapes then go through ``GetPlayerSummaries``
(:func:`~yupay.modules.auth.steam.fetch_persona`) for the nickname/avatar —
and here the rule is uniform, deliberately not shape-dependent:
**``"found"`` is returned only when Steam actually gave us a persona;
anything less is ``"unavailable"``.** ``fetch_persona`` is best-effort and
degrades to ``(None, None)`` on *any* failure, transient or not — exactly
the "nameless, not broken" degrade it already gives Steam sign-in, where
that is fine because OpenID has already cryptographically proven the
identity before ``fetch_persona`` ever runs. Nothing has proven identity
here, so an empty answer cannot be read as "found": it means we confirmed
nothing the buyer can act on — no avatar, no nickname, nothing to render —
regardless of whether a vanity resolved a moment earlier. The deliverable
of this whole endpoint is the avatar and the nickname; a verdict carrying
neither has to read as "we couldn't check," not "found."

Redis caches ``"found"``/``"not_found"`` verdicts for 6h under
``gifts:steam_profile:{steamid_or_vanity}`` (see
``docs/architecture/cache-keys.md``) — profiles change rarely.
``"unavailable"`` is never cached: it is our failure, not a fact about the
profile, and caching it would keep telling the next buyer the same lie —
this is exactly why the persona-empty case above must resolve to
``"unavailable"`` before the cache write, not after.

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
    # Steam documents only two values: `1` (resolved) and `42` ("No match").
    # Treating every other value as "no match" too is deliberate, not an
    # oversight -- there is nothing else a definitive verdict could mean,
    # and it keeps this module from having to track Steam's undocumented
    # error codes to stay correct.
    if body.get("success") == 1:
        steamid = body.get("steamid")
        if isinstance(steamid, str) and steamid:
            return steamid
        raise ValueError("ResolveVanityURL reported success without a steamid")
    return None


def _describe_error(exc: Exception) -> str:
    """A log-safe description of a failed Steam call. Never ``str(exc)``.

    Both Steam calls in this module carry ``key=<our api key>`` in the
    request's query string, and ``httpx.HTTPStatusError.__str__`` embeds
    the full request URL — query string included. Logging that verbatim
    would leak the key into every log line for a Steam 4xx/5xx, the exact
    class of bug this module's own docstring already flags for Waxpeer
    (see ``core/logging.py``). This keeps only what is safe: the exception
    type, plus the HTTP status code when the exception carries one.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status is not None:
        return f"{type(exc).__name__} ({status})"
    return type(exc).__name__


async def _resolve_and_summarise(
    *, is_vanity: bool, identifier: str, api_key: str, client: httpx.AsyncClient
) -> GiftProfileOut:
    """Run the Steam call(s) for one already-cache-missed identifier.

    Split out of :func:`check_steam_profile` so that function stays under
    the return-statement budget (ruff ``PLR0911``) — this is where every
    Steam-side branch (``not_found``, ``unavailable`` from an exception,
    ``unavailable`` from an empty persona, ``found``) actually lives.
    Never raises and never touches the cache; the caller decides what of
    this is worth caching.
    """
    try:
        if is_vanity:
            resolved = await _resolve_vanity(identifier, api_key=api_key, http=client)
            if resolved is None:
                return _NOT_FOUND
            steam_id = resolved
        else:
            steam_id = identifier
        nickname, avatar_url = await fetch_persona(int(steam_id), api_key=api_key, http=client)
    except Exception as exc:  # noqa: BLE001 -- a Steam problem is `unavailable`, never a 500
        log.warning(
            "gifts.steam_profile_unavailable",
            identifier_hash=_hash_short(identifier),
            error=_describe_error(exc),
        )
        return _UNAVAILABLE

    if nickname is None and avatar_url is None:
        # Uniform across both shapes (see the module docstring and
        # `check_steam_profile`'s own docstring): `found` means Steam
        # actually gave us something to render. `fetch_persona` swallows
        # its own failures into `(None, None)`, so this is also where a
        # transient `GetPlayerSummaries` outage lands -- correctly, since
        # `unavailable` is never cached and `found` would otherwise poison
        # the 6h cache with a permanent, empty "confirmation".
        log.info(
            "gifts.steam_profile_unavailable",
            identifier_hash=_hash_short(identifier),
            reason="persona_empty",
        )
        return _UNAVAILABLE

    log.info("gifts.steam_profile_found", identifier_hash=_hash_short(identifier))
    return GiftProfileOut(
        status="found", steam_id=steam_id, nickname=nickname, avatar_url=avatar_url
    )


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

    ``"found"`` is returned only when Steam actually gave us a persona —
    a non-empty nickname or avatar from ``GetPlayerSummaries`` — for
    *either* the ``/profiles/`` or the ``/id/{vanity}`` shape; anything
    less is ``"unavailable"``. This is deliberately uniform rather than
    shape-dependent: the deliverable of this endpoint is the avatar and
    the nickname, so a verdict carrying neither has confirmed nothing the
    buyer can act on, whether or not a vanity happened to resolve a moment
    earlier.

    Args:
        invite_url: the raw ``invite_url`` the caller posted, any of the shapes
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
    # ValueError alongside RedisError: `model_validate_json` raises
    # `pydantic.ValidationError` (a `ValueError` subclass) on a schema
    # mismatch and `json.JSONDecodeError` (also a `ValueError` subclass) on
    # unparseable JSON. A stale/malformed blob under this key -- e.g. from a
    # future schema change -- must degrade like a cache miss, not become a
    # 500 on an endpoint whose entire point is to never be the reason a
    # request fails.
    with contextlib.suppress(RedisError, ValueError):
        cached = await redis.get(cache_key)
        if cached is not None:
            return GiftProfileOut.model_validate_json(cached)

    api_key = get_settings().steam_api_key
    if not api_key:
        return _UNAVAILABLE

    client = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    try:
        out = await _resolve_and_summarise(
            is_vanity=is_vanity, identifier=identifier, api_key=api_key, client=client
        )
    finally:
        if http is None:
            await client.aclose()

    # `not_found`/`found` are facts about the profile, cached for 6h;
    # `unavailable` is our own failure and is never written (see the
    # module docstring).
    if out.status in ("found", "not_found"):
        await _cache_verdict(redis, cache_key, out)
    return out


__all__ = ["check_steam_profile"]
