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
  that it is 17 digits, not that such an account has ever existed. The
  ``GetPlayerSummaries`` call below is the only existence check this shape
  gets — and it is the shape Steam's own "Copy profile URL" button hands to
  every user without a custom URL, so it is roughly half the links this
  endpoint sees.
- ``steamcommunity.com/id/{vanity}`` — resolved via
  ``ISteamUser/ResolveVanityURL/v1/``. This is the one Steam call in the
  whole flow allowed to answer definitively that a link does *not* exist,
  and it only does so on Steam's documented "No match": ``success == 42``
  becomes ``"not_found"``. ``success == 1`` resolves; every other value,
  documented or not, is ``"unavailable"`` along with anything else about
  that call failing (see :func:`_resolve_vanity`).
- ``s.team/p/{path}`` — a friend-invite token, not a profile. The Web API
  cannot resolve these at all, so this is ``"unsupported"`` with no Steam
  call made, ever.

Both of the first two shapes then go through ``GetPlayerSummaries``
(:func:`~yupay.modules.auth.steam.resolve_persona`), which keeps three
outcomes apart that this module must not confuse:

- an empty ``players`` array — Steam *answering* that no account holds this
  steamid64 — is ``"not_found"``, uniformly for both shapes;
- a player row carrying neither a name nor an avatar is ``"unavailable"``:
  the deliverable of this endpoint is the avatar and the nickname, so a
  verdict with neither confirms nothing the buyer can act on, and a green
  card wrapped around an empty name would sit cached for 6h;
- anything that stopped the call landing at all — timeout, 5xx, unparseable
  body — is ``"unavailable"`` too.

**``"found"`` still requires a persona.** What changed (2026-09-04 final
review) is that the true negative is now expressible for the ``/profiles/``
shape as well. That is why :func:`~yupay.modules.auth.steam.resolve_persona`
exists rather than ``fetch_persona``: the latter is best-effort and flattens
all three outcomes into ``(None, None)``, which is exactly right for Steam
sign-in — OpenID has already cryptographically proven the account exists
before it runs — and exactly wrong here, where it made a mistyped digit
answer «Steam сейчас не отвечает — можно продолжить» and the buyer pay for a
gift that went nowhere.

Redis caches ``"found"``/``"not_found"`` verdicts for 6h under
``gifts:steam_profile:{id|sid}:{vanity_or_steamid}`` (see
``docs/architecture/cache-keys.md``) — profiles change rarely. **The
namespace is load-bearing:** every steamid64 is also a syntactically valid
vanity name, so a shared namespace let one unauthenticated
``/id/{17 digits}`` request poison the verdict for the genuine
``/profiles/{same digits}``. ``"unavailable"`` is never cached: it is our
failure, not a fact about the profile, and caching it would keep telling
the next buyer the same lie.

PII note: ``steam_id``/nickname/avatar never appear in a log call here —
only an opaque hash of the link's own identifier, the same convention
``integrations.player_check`` uses for ``player_id``.
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError

from yupay.core.config import get_settings
from yupay.core.logging import get_logger, hash_short
from yupay.core.redis import get_redis
from yupay.modules.auth.steam import resolve_persona
from yupay.modules.gifts.checkout import parse_invite_url
from yupay.modules.gifts.schemas import GiftProfileOut

log = get_logger("yupay.gifts.profile")

_RESOLVE_VANITY_URL = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
#: Per-operation httpx timeout for one Steam call.
_TIMEOUT_SECONDS = 5.0
#: Ceiling on ALL the Steam work for one request. The vanity path makes two
#: sequential calls and ``_TIMEOUT_SECONDS`` is per-operation, so without this
#: the server's worst case (~10 s) sat *above* the 8 s both frontends allow
#: before they abort and report «Steam не отвечает» — while this side went on
#: to finish and cache a `found` the buyer never saw (2026-09-04 final
#: review). Kept below the client budget so the client's abort is the outer
#: bound, not the inner one.
_TOTAL_BUDGET_SECONDS = 7.0
_CACHE_TTL_SECONDS = 6 * 3600

_PROFILE_PREFIX = "https://steamcommunity.com/profiles/"
_VANITY_PREFIX = "https://steamcommunity.com/id/"
_S_TEAM_PREFIX = "https://s.team/"

_UNAVAILABLE = GiftProfileOut(status="unavailable", steam_id=None, nickname=None, avatar_url=None)
_UNSUPPORTED = GiftProfileOut(status="unsupported", steam_id=None, nickname=None, avatar_url=None)
_NOT_FOUND = GiftProfileOut(status="not_found", steam_id=None, nickname=None, avatar_url=None)

#: ``ResolveVanityURL``'s documented "No match" code — one of the two signals
#: allowed to become ``status="not_found"``. See :func:`_resolve_vanity`.
_RESOLVE_NO_MATCH = 42

#: Cache-key namespaces, one per canonical link shape. **Not optional:**
#: ``_STEAM_ID64_RE`` is ``\d{17}`` and ``_STEAM_VANITY_RE`` is
#: ``[A-Za-z0-9_-]{2,32}``, so every steamid64 is also a syntactically valid
#: vanity name. Sharing one namespace let a single unauthenticated
#: ``/id/{17 digits}`` request file a ``not_found`` that then answered for the
#: genuine ``/profiles/{same digits}`` — a six-hour denial of purchase against
#: any Steam account — and, the other way round, replayed a stranger's
#: ``found`` card as the buyer's recipient (2026-09-04 final review).
_KEY_NS_VANITY = "id"
_KEY_NS_STEAM_ID = "sid"


async def _resolve_vanity(vanity: str, *, api_key: str, http: httpx.AsyncClient) -> str | None:
    """Resolve a vanity name to a steamid64 via ``ISteamUser/ResolveVanityURL/v1/``.

    Args:
        vanity: the ``{vanity}`` path segment from a canonical
            ``steamcommunity.com/id/{vanity}`` link.
        api_key: our Steam Web API key.
        http: the client to issue the request on.

    Returns:
        The resolved steamid64, or ``None`` on Steam's own documented
        ``success == 42`` ("No match") answer — the single signal in this
        whole module allowed to become ``status="not_found"``.

    Raises:
        httpx.HTTPError: transport failure or a non-2xx response.
        ValueError: the response body was 200 but not shaped like a
            ``ResolveVanityURL`` answer — ``success == 1`` with no
            ``steamid``, or any ``success`` value Steam does not document.
            The caller folds every one of these into ``"unavailable"`` —
            they mean "we could not ask", never "we asked and Steam said
            no".
    """
    resp = await http.get(_RESOLVE_VANITY_URL, params={"key": api_key, "vanityurl": vanity})
    resp.raise_for_status()
    body = resp.json().get("response", {})
    success = body.get("success")
    if success == 1:
        steamid = body.get("steamid")
        if isinstance(steamid, str) and steamid:
            return steamid
        raise ValueError("ResolveVanityURL reported success without a steamid")
    # Steam documents exactly two values: `1` (resolved) and `42` ("No
    # match"). Only `42` becomes `not_found`. An undocumented value means we
    # could not get an answer -- the same class of event as a timeout or a
    # 500, which this module already calls `unavailable` -- and this call is
    # the module's ONLY producer of `not_found`, the only verdict that
    # hard-blocks a paying buyer with no override in either UI. The one
    # blocking verdict earns the strictest evidence: unknown means unknown
    # (2026-09-04 review round 1; this used to read every non-`1` value as a
    # definitive "no such profile").
    if success == _RESOLVE_NO_MATCH:
        return None
    raise ValueError("ResolveVanityURL returned an undocumented success value")


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
    *,
    is_vanity: bool,
    identifier: str,
    api_key: str,
    client: httpx.AsyncClient,
    budget_seconds: float,
) -> GiftProfileOut:
    """:func:`_steam_verdict` under a deadline, with every raise folded away.

    Never raises and never touches the cache. The deadline spans *both* Steam
    calls: ``_TIMEOUT_SECONDS`` is per-operation, so the vanity path could
    otherwise run past the 8 s budget both frontends allow before they abort
    and tell the buyer «Steam не отвечает» — while this side went on to finish
    and cache a ``found`` nobody ever saw.

    Args:
        is_vanity: whether ``identifier`` is a vanity name.
        identifier: the tail of the canonical link.
        api_key: our Steam Web API key.
        client: the HTTP client both Steam calls share.
        budget_seconds: ceiling on all the Steam work for this request.

    Returns:
        The verdict; ``unavailable`` for anything that failed or timed out.
    """
    try:
        async with asyncio.timeout(budget_seconds):
            return await _steam_verdict(
                is_vanity=is_vanity, identifier=identifier, api_key=api_key, client=client
            )
    except Exception as exc:  # noqa: BLE001 -- a Steam problem is `unavailable`, never a 500
        log.warning(
            "gifts.steam_profile_unavailable",
            identifier_hash=hash_short(identifier),
            error=_describe_error(exc),
        )
        return _UNAVAILABLE


async def _steam_verdict(
    *, is_vanity: bool, identifier: str, api_key: str, client: httpx.AsyncClient
) -> GiftProfileOut:
    """The Steam call(s) themselves, for one already-cache-missed identifier.

    Raises freely — transport failure, a non-2xx, an unparseable body, an
    undocumented ``ResolveVanityURL`` code. :func:`_resolve_and_summarise` is
    what turns every one of those into ``unavailable``. Touches no cache; the
    caller decides what of this is worth keeping.

    Args:
        is_vanity: whether ``identifier`` is an ``/id/{vanity}`` name rather
            than a ``/profiles/{steamid64}`` id.
        identifier: the tail of the canonical link.
        api_key: our Steam Web API key.
        client: the HTTP client both Steam calls share.

    Returns:
        The verdict — ``not_found`` (Steam said no, either call),
        ``unavailable`` (Steam has the account but nothing to render), or
        ``found``.
    """
    if is_vanity:
        resolved = await _resolve_vanity(identifier, api_key=api_key, http=client)
        if resolved is None:
            return _NOT_FOUND
        steam_id = resolved
    else:
        steam_id = identifier
    persona = await resolve_persona(int(steam_id), api_key=api_key, http=client)

    if persona is None:
        # A 200 carrying `players: []` -- Steam answering that no account
        # holds this steamid64. For a `/profiles/` link this is the only
        # existence check there is, and it is the shape Steam's own "Copy
        # profile URL" hands to every user without a custom URL. Folding it
        # in with the timeouts told those buyers «Steam сейчас не отвечает --
        # можно продолжить» about a profile that does not exist, and they
        # paid for a gift that went nowhere (2026-09-04 final review).
        # Uniform across both shapes: whatever produced the id a moment
        # earlier, this is Steam's answer about the id itself.
        log.info("gifts.steam_profile_not_found", identifier_hash=hash_short(identifier))
        return _NOT_FOUND

    nickname, avatar_url = persona
    if nickname is None and avatar_url is None:
        # Steam HAS this account but handed us nothing to render. Distinct
        # from the branch above, and deliberately still not `found`: the
        # deliverable of this endpoint is the avatar and the nickname, so a
        # verdict carrying neither confirms nothing the buyer can act on, and
        # a green card wrapped around an empty name would sit cached for 6h.
        # `unavailable` (never cached) is the honest answer.
        log.info(
            "gifts.steam_profile_unavailable",
            identifier_hash=hash_short(identifier),
            reason="persona_empty",
        )
        return _UNAVAILABLE

    log.info("gifts.steam_profile_found", identifier_hash=hash_short(identifier))
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

    namespace = _KEY_NS_VANITY if is_vanity else _KEY_NS_STEAM_ID
    # Namespaced by link shape -- see `_KEY_NS_VANITY`. The two accept-sets
    # overlap completely on 17-digit strings, so one namespace meant one
    # entry with two meanings.
    cache_key = f"gifts:steam_profile:{namespace}:{identifier}"
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
        # The deadline covers both Steam calls together. `_resolve_and_summarise`
        # catches the resulting `TimeoutError` itself (it catches `Exception`)
        # and answers `unavailable`, so this cannot become a 500 on an endpoint
        # whose whole point is never to be the reason a request fails.
        out = await _resolve_and_summarise(
            is_vanity=is_vanity,
            identifier=identifier,
            api_key=api_key,
            client=client,
            budget_seconds=_TOTAL_BUDGET_SECONDS,
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
