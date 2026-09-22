"""Storefront player-id verification (G2B nickname lookup / Waxpeer Steam
login check), with a NOVA second opinion when the primary answers ``error``.

Advisory: for a ``g2b``-checked field, resolves the brand's G2B
``game_code`` from its supplier mapping and proxies ``games_check_player``.
For a ``waxpeer``-checked field, proxies ``WaxpeerClient.validate_login`` —
Steam has no game_code/mapping to resolve, the login itself is the lookup
key. Either way the result carries the same three-way ``status``
(``valid``/``invalid``/``error``); faults degrade to ``status="error"`` so the
storefront never hits an error boundary. See ADR-0031.

An ``error`` from the primary — G2B rate-limited us, refused, or could not
be reached, or the same for Waxpeer — is retried once against NOVA
(``player_check_nova``) before it reaches the caller. The fallback can turn
that ``error`` into ``valid``; it never turns anything into ``invalid`` — only
the primary's own verdict may block Pay.

**The Steam pair runs NOVA-first, not Waxpeer-first, since 2026-09-22.**
Every other pair here has G2B or Waxpeer as the primary and NOVA as the
"no verdict at all" fallback — Steam had that shape too, until Waxpeer's
``/steam-topup/validate`` started answering ``valid: false`` for every
login it was asked about, known-good Steam accounts (five already-delivered
orders) included. That is a ``200`` with a boolean body, not a fault, so it
never raised and the old ``error``-only fallback never ran: every Steam
check failed closed, which blocks Pay. NOVA cannot say ``invalid`` either
(``player_check_nova.fallback_for_steam``'s own contract) — while Waxpeer is
in this state, nothing here can confidently reject a login, which is the
honest answer, and better than rejecting all of them. Waxpeer is still
consulted when NOVA itself cannot answer, so a genuine Waxpeer verdict
still reaches a customer on that path. Swap the two calls back in
:func:`check_player_for_brand_id` once Waxpeer's validate is fixed.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, Protocol

from sqlalchemy import select

from yupay.core.errors import NotFoundError, ValidationError
from yupay.core.logging import get_logger, hash_short
from yupay.core.redis import get_redis
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.integrations.breaker import SupplierBreaker
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.integrations.schemas import PlayerCheckOut

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger("yupay.integrations.player_check")

_CACHE_TTL_SECONDS = 300


def _worth_caching(out: PlayerCheckOut) -> bool:
    """Only a ``valid`` verdict is remembered.

    A verdict is the supplier's word at one instant, and the word is not
    stable: Waxpeer has answered ``valid: false`` for a login it accepted on
    the next call — observed on the owner's own account. ``invalid`` is the one
    answer that blocks Pay, so caching a wrong one turned a supplier hiccup
    into a five-minute dead checkout that a re-check could not clear: the
    storefront asked again, and we answered from Redis. ``error`` is the same
    shape with a different cause (G2B's ``_map_response`` yields it for a body
    it cannot read, and that was being cached too).

    A positive is safe to keep — a login that exists does not stop existing
    inside 300 s — and it is the case the cache was for: repeat taps on a good
    id stay off the supplier. Negatives re-ask; the route's own rate bucket and
    the breaker already bound how often that can happen.
    """
    return out.status == "valid"


#: Consecutive upstream failures that stop us calling G2B for a while, and how
#: long that lasts. Tuned for an *advisory* check: three is short enough that a
#: real outage is caught within a few customers, and 30s is short enough that a
#: brief blip costs almost nobody a check — the first request after it expires
#: goes through for real and closes the circuit if the supplier recovered.
#: See ADR-0059 for why this guards the check and not fulfilment.
_BREAKER_THRESHOLD = 3
_BREAKER_COOLDOWN_SECONDS = 30

_KNOWN_PROVIDERS = ("g2b", "waxpeer")


def _field_of(required_fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The first form field that opts into a supported check, or ``None``."""
    for f in required_fields:
        if (
            isinstance(f, dict)
            and isinstance(f.get("check"), dict)
            and f["check"].get("provider") in _KNOWN_PROVIDERS
        ):
            return f
    return None


def _agreed_field(fields: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One check config every product of a brand agrees on, or ``None``.

    Agreement is on the three things the check actually reads: provider, the
    sibling server field and the id field's key. Anything else differing
    between products (labels, patterns) does not change what is checked.
    """
    if not fields:
        return None
    first = fields[0]

    def _sig(f: dict[str, Any]) -> tuple[Any, Any, Any]:
        return (f["check"].get("provider"), f["check"].get("server_field"), f.get("key"))

    return first if all(_sig(f) == _sig(first) for f in fields[1:]) else None


async def brand_check_field(session: AsyncSession, brand_id: str) -> dict[str, Any] | None:
    """The check-bearing form field of a brand, or ``None``.

    ``None`` covers both "no product of this brand declares a check" and
    "its products disagree on the check" — the second is logged, because it is
    a catalog mistake someone has to fix, not a brand that never wanted one.

    Columns, not entities: ``Product`` configures selectin relationships that
    would drag the whole retail subtree through an advisory lookup.
    """
    rows = (
        await session.execute(
            select(Product.required_fields).where(
                Product.brand_id == brand_id, Product.active.is_(True)
            )
        )
    ).all()
    fields = [f for (rf,) in rows if (f := _field_of(list(rf or []))) is not None]
    if not fields:
        return None
    agreed = _agreed_field(fields)
    if agreed is None:
        logger.warning(
            "player_check_brand_config_mismatch",
            brand_id=brand_id,
            hint="the brand's products declare different `check` configs; a brand "
            "is one game (ADR-0079), so they must agree — no check until they do",
        )
    return agreed


#: The only two things G2B's ``valid`` field is allowed to say. Anything else
#: — a missing key, a renamed one, a third token, a null — is a shape we do not
#: understand, and understanding it is the whole job here.
_G2B_VERDICTS = frozenset({"valid", "invalid"})


def _map_response(resp: dict[str, Any]) -> PlayerCheckOut:
    """Map a successful G2B ``checkPlayerId`` body to a public result.

    **A verdict we recognise, or none at all.** ``"valid"`` is a real hit and
    ``"invalid"`` is the customer's mistake; every other body — the key absent,
    the key renamed, a third token nobody told us about — is ``"error"``,
    because it means the supplier answered and we could not read the answer.

    This used to collapse the unrecognised case into ``"invalid"``, which made
    the check a fake **rejecter**: the mirror of the fake approver the whole
    three-way status exists to prevent, and the louder failure of the two. If
    G2B renamed this field, every call would still be an HTTP 200, no breaker
    would fire, nothing would be logged as a failure — and every player id on
    the platform would come back "no such player", telling every customer and
    every reseller that they had mistyped. ``"error"`` says what is true: we
    could not check. (The client already tolerates three different list keys on
    ``fetch_products``, so this supplier's shape drifting is not hypothetical.)

    Args:
        resp: The parsed 200 body, or the verdict body unwrapped from a 400 by
            ``g2b_client.games_check_player``.

    Returns:
        The three-way advisory result.
    """
    verdict = str(resp.get("valid") or "").strip().lower()
    if verdict not in _G2B_VERDICTS:
        logger.warning(
            "player_check_unrecognised_verdict",
            provider="g2b",
            keys=sorted(str(k) for k in resp)[:10],
            hint="G2B answered 200 with no verdict we recognise in `valid`; "
            "reporting `error` rather than telling every customer they mistyped. "
            "If their wire format changed, `_G2B_VERDICTS` is where it is read.",
        )
        return PlayerCheckOut(status="error")
    if verdict == "valid":
        return PlayerCheckOut(status="valid", name=str(resp["name"]) if resp.get("name") else None)
    return PlayerCheckOut(status="invalid")


#: Brands G2B can *validate* for us but does not *sell* for us.
#:
#: A brand-keyed table rather than a mapping row, for the same reason
#: ``player_check_nova.NOVA_VALIDATE`` is one: validation is brand-scoped
#: where a mapping is SKU-scoped, and the two answer different questions.
#: Coupling them means a brand can only be checked by a supplier we happen to
#: buy from, which is not a rule anybody chose — it is just how the lookup was
#: written.
#:
#: ``telegram-stars`` is the case that made the difference visible. G2B sells
#: Stars only in fixed packs, so it is deliberately not a channel for the
#: free-amount line the storefront actually renders — and yet its
#: ``checkPlayerId`` answers for a Telegram username perfectly well
#: (confirmed 2026-09-20 against a real handle, which came back
#: ``{"valid": "valid", "name": ...}``). Without this table the field could
#: not be checked at all, for want of a mapping we do not want.
#:
#: ``telegram-premium`` is absent on purpose: it *does* have a G2B mapping on
#: the same ``Telegram`` game, so the scan below already finds its code. One
#: source per brand, and the live mapping wins.
G2B_VALIDATE_ONLY: dict[str, str] = {
    "telegram-stars": "Telegram",
}


async def resolve_g2b_game_code(session: AsyncSession, brand_id: str) -> str | None:
    """The G2B game_code for a brand: the one ``external_product_id`` across
    its active ``g2b/game`` mappings, or :data:`G2B_VALIDATE_ONLY` for a brand
    G2B can check but does not sell for us.

    A brand is exactly one supplier game (ADR-0079). Two distinct codes means
    the catalog is mid-migration or misconfigured, and picking one would
    validate a player against the wrong region's game and answer "invalid"
    for a perfectly good id — so two codes is no check rather than a wrong one.
    The scan covers active products only, same as :func:`brand_check_field`:
    an inactive product cannot be bought, so its mapping's code is never a
    candidate — a retired region left mapped stays retired here too.
    """
    stmt = (
        select(SkuSupplierMapping.external_product_id)
        .join(Sku, Sku.id == SkuSupplierMapping.sku_id)
        .join(Product, Product.id == Sku.product_id)
        .where(
            Product.brand_id == brand_id,
            Product.active.is_(True),
            SkuSupplierMapping.supplier_slug == "g2b",
            SkuSupplierMapping.kind == "game",
            SkuSupplierMapping.is_active.is_(True),
        )
        .distinct()
        .limit(2)
    )
    codes = list((await session.execute(stmt)).scalars().all())
    if len(codes) > 1:
        logger.warning(
            "player_check_brand_spans_games",
            brand_id=brand_id,
            codes=sorted(codes),
            hint="one brand maps to two G2B games; split it (see ADR-0079) — "
            "every check on it answers `error` until then",
        )
        return None
    if not codes:
        brand_slug = (
            await session.execute(select(Brand.slug).where(Brand.id == brand_id))
        ).scalar_one_or_none()
        override = G2B_VALIDATE_ONLY.get(str(brand_slug or ""))
        if override is not None:
            return override
        logger.warning(
            "player_check_no_game_mapping",
            brand_id=brand_id,
            hint="this brand's form declares a g2b player check but no active "
            "sku_supplier_mapping (supplier_slug='g2b', kind='game') exists on any "
            "of its SKUs, so every check answers `error`; add the mapping or drop the "
            "check from the form",
        )
        return None
    return codes[0]


def _cache_key(game_code: str, player_id: str, server_id: str | None) -> str:
    """Redis key for a cached g2b player-check result.

    ``player_id`` is hashed (never stored raw) so the key carries no PII —
    it would otherwise be plaintext-visible via ``MONITOR``/``SCAN`` (§9).
    ``hash_short`` is deterministic, so identical inputs still cache-hit.
    """
    return f"playercheck:g2b:{game_code}:{server_id or '-'}:{hash_short(player_id)}"


def _waxpeer_cache_key(steam_login: str) -> str:
    """Redis key for a cached Steam-login check result.

    Same PII rule as :func:`_cache_key`: ``steam_login`` is personal data and
    is hashed, never stored raw, in the key. A distinct ``waxpeer:`` prefix
    keeps this namespace from ever colliding with a g2b ``player_id`` cache
    entry even if the raw strings happened to match.
    """
    return f"playercheck:waxpeer:{hash_short(steam_login)}"


async def _cached(key: str) -> PlayerCheckOut | None:
    """A previously cached verdict, or ``None`` to go and ask the supplier.

    The **parse** is inside the guard, not only the ``GET``. A cache entry
    written by an older shape of ``PlayerCheckOut`` — or half-written, or
    hand-edited — would otherwise raise ``ValidationError`` out of a function
    whose docstring promises it never raises, turning an advisory lookup into a
    500 for as long as the entry lives. Falling through costs one supplier
    call.

    Args:
        key: The Redis key, already namespaced and PII-hashed by the caller.

    Returns:
        The cached result, or ``None`` when there is none we can use.
    """
    try:
        raw = await get_redis().get(key)
        return PlayerCheckOut.model_validate_json(raw) if raw else None
    except Exception:  # noqa: BLE001 — cache is best-effort, in both directions
        return None


class _LoginClient(Protocol):
    """What ``_client()`` needs to return: a Waxpeer client's login check."""

    async def validate_login(self, steam_login: str) -> tuple[bool, str | None]: ...


class _LoginChecker(Protocol):
    """What the check needs from a Waxpeer client; a Protocol so the unit test can script it."""

    def _client(self) -> _LoginClient: ...


async def _check_waxpeer_login(
    fulfiller: _LoginChecker | None, *, steam_login: str
) -> PlayerCheckOut:
    """Validate a Steam login via ``WaxpeerClient.validate_login``.

    Same three-way contract as the g2b path: Waxpeer says the login is
    supported -> ``status="valid"`` (Steam has no display name, so ``name``
    stays ``None``); Waxpeer answers ``valid: false`` and the login isn't
    supported -> ``status="invalid"`` (the customer's mistake, not a fault);
    anything else — unconfigured, network/API failure, or a body carrying no
    boolean ``valid`` at all, which ``validate_login`` raises on for the same
    reason :func:`_map_response` refuses an unrecognised token — is
    ``status="error"``, never raised.
    """
    redis = get_redis()
    key = _waxpeer_cache_key(steam_login)
    cached = await _cached(key)
    if cached is not None:
        return cached

    if fulfiller is None:
        return PlayerCheckOut(status="error")

    try:
        valid, reason = await fulfiller._client().validate_login(steam_login)
    except Exception as exc:  # noqa: BLE001 — advisory; degrade, never 500
        logger.warning(
            "player_check_failed",
            provider="waxpeer",
            player_id_hash=hash_short(steam_login),
            error=str(exc)[:200],
        )
        return PlayerCheckOut(status="error")

    out = PlayerCheckOut(status="valid") if valid else PlayerCheckOut(status="invalid")
    if _worth_caching(out):
        with contextlib.suppress(Exception):  # cache is best-effort
            await redis.set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    # ``reason`` is Waxpeer's own ``msg`` on a negative — not the login, not
    # PII. It was being discarded, which is why an intermittent ``false`` on a
    # good login left no trace to tell "no such profile" from "try again".
    logger.info(
        "player_check",
        provider="waxpeer",
        player_id_hash=hash_short(steam_login),
        status=out.status,
        reason=(reason or "")[:120] if not valid else None,
    )
    return out


def _counts_against_supplier(exc: BaseException) -> bool:
    """Whether ``exc`` says something about G2B's *health*.

    The breaker exists to stop customers paying the client's 1→2→4→8s retry
    budget, so what it must react to is failures that involve that budget:
    network errors and exhausted retries, both of which surface as
    ``UpstreamUnavailableError``.

    A non-retryable 4xx does not qualify. "Unknown game" is one brand's broken
    mapping, it is raised immediately with no backoff to save, and counting it
    would let a single misconfigured product silence the check for every other
    brand — the circuit is shared across the supplier, not per game.

    401 is the exception to that exception. It also fails fast, so no customer
    is waiting on it, but the client's own warning is that a few in a row get
    our IP banned at G2B — and that ban would take order *fulfilment* down
    with it. Backing off a rejected key protects the money path.
    """
    from yupay.modules.fulfillment.suppliers.g2b_client import G2bError

    if isinstance(exc, G2bError):
        return exc.status == 401
    return True


def _breaker_for_g2b() -> SupplierBreaker:
    """The circuit guarding the G2B player check.

    Built per call rather than held as a module global: the object carries no
    state of its own (it all lives in Redis), and a module-level instance
    would freeze the thresholds at import time, which the tests re-read.
    """
    return SupplierBreaker(
        "g2b:player_check",
        threshold=_BREAKER_THRESHOLD,
        cooldown_seconds=_BREAKER_COOLDOWN_SECONDS,
    )


CODE_BRAND_NOT_FOUND = "brand_not_found"


async def check_player_for_brand(
    session: AsyncSession,
    *,
    brand_slug: str,
    player_id: str,
    server_id: str | None,
) -> PlayerCheckOut:
    """Verify a player id (or Steam login) for a brand. Never raises on a
    supplier fault; raises only for a brand that does not exist or is not
    checkable, which are the caller's mistakes.

    Args:
        session: Session. Rolled back before a Waxpeer call, as before.
        brand_slug: The brand's public slug, as in ``/catalog/brands``.
        player_id: The customer's identifier — never logged, only hashed.
        server_id: The sibling server value, where the form declares one.

    Returns:
        The three-way advisory verdict.
    """
    row = (
        await session.execute(
            select(Brand.id).where(Brand.slug == brand_slug, Brand.active.is_(True))
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("brand not found", code=CODE_BRAND_NOT_FOUND)
    return await check_player_for_brand_id(
        session, brand_id=row.id, player_id=player_id, server_id=server_id
    )


async def check_player_for_brand_id(
    session: AsyncSession,
    *,
    brand_id: str,
    player_id: str,
    server_id: str | None,
) -> PlayerCheckOut:
    """As :func:`check_player_for_brand`, for a caller that already has the id.

    An ``error`` from the primary is retried once against NOVA before it
    reaches the caller — for a game brand, G2B is primary. For a Steam
    login the pair runs the other way round since 2026-09-22 (Waxpeer's own
    validate started rejecting every login, including known-good ones): NOVA
    is primary there, and Waxpeer is the one retried on an ``error``. See
    the module docstring and ``player_check_nova``.
    """
    from yupay.modules.integrations.routes import _waxpeer_fulfiller_or_none

    field = await brand_check_field(session, brand_id)
    if field is None:
        raise ValidationError("brand is not checkable")

    if field["check"]["provider"] == "waxpeer":
        await session.rollback()
        # NOVA primary, Waxpeer as the fallback — the reverse of every other
        # pair here, and deliberately so since 2026-09-22. Waxpeer's own
        # `/steam-topup/validate` started answering `valid: false` for
        # literally every login, ours and known-good Steam accounts alike —
        # a real upstream regression, not a customer's typo, confirmed
        # against five logins from already-delivered orders. It never raised
        # (a 200 with a boolean body is not a fault), so the old
        # `error`-only fallback never triggered and every Steam check failed
        # closed, which blocks Pay (ADR-0031). `_nova_steam` cannot say
        # `invalid` either (see its own docstring) — the honest state while
        # Waxpeer is in this mode is that *nothing* can confidently reject a
        # login, so nothing does, which beats rejecting all of them.
        #
        # Waxpeer is still asked when NOVA cannot answer at all (breaker
        # open, unconfigured, network failure) — a real Waxpeer verdict,
        # `valid` or `invalid`, is better than none, and this is the one
        # path where a Waxpeer `invalid` can still reach a customer. Revert
        # by swapping the two calls back once Waxpeer's validate is fixed —
        # nothing else here depends on which one goes first.
        out = await _nova_steam(player_id)
        return (
            out
            if out.status != "error"
            else await _check_waxpeer_login(_waxpeer_fulfiller_or_none(), steam_login=player_id)
        )

    out = await _check_g2b_player(
        session, brand_id=brand_id, player_id=player_id, server_id=server_id
    )
    if out.status != "error":
        return out

    # Only read on this path, not up front: this query runs solely on the
    # `error` branch that reaches for NOVA anyway, which keeps the common
    # `valid`/`invalid` path at the query count
    # `test_the_check_does_not_fan_out_over_the_catalog` pins.
    brand_slug = (
        await session.execute(select(Brand.slug).where(Brand.id == brand_id))
    ).scalar_one_or_none()
    # And then hand the connection back, for the reason `_check_g2b_player`
    # gives at its own rollback: the pool is twenty connections for the whole
    # process, and a supplier call made while holding one is how a slow
    # supplier becomes an outage. The read above *autobegins* a transaction —
    # a rollback ends a transaction, not the session, so the session happily
    # starts a new one — which means without this line the NOVA round trip
    # below would run holding a connection the G2B call had just released.
    #
    # It also covers the two exits above that never reached that rollback at
    # all: `_check_g2b_player` returns `error` early when the brand has no
    # active G2B mapping and when the adapter is unconfigured, and the first
    # of those is a routine, permanent state for a brand rather than an
    # outage-only one.
    await session.rollback()
    return await _nova_brand(brand_slug, player_id, server_id)


async def _nova_brand(
    brand_slug: str | None, player_id: str, server_id: str | None
) -> PlayerCheckOut:
    """Second opinion when the primary could not answer. Never ``invalid``."""
    from yupay.modules.integrations.player_check_nova import fallback_for_brand

    return await fallback_for_brand(brand_slug=brand_slug, player_id=player_id, server_id=server_id)


async def _nova_steam(steam_login: str) -> PlayerCheckOut:
    """As :func:`_nova_brand`, for the Steam-login branch."""
    from yupay.modules.integrations.player_check_nova import fallback_for_steam

    return await fallback_for_steam(steam_login=steam_login)


async def _check_g2b_player(
    session: AsyncSession,
    *,
    brand_id: str,
    player_id: str,
    server_id: str | None,
) -> PlayerCheckOut:
    """The G2B half of the check: game code, cache, circuit, upstream call.

    Split out of ``check_player_for_brand`` so that function stays a
    provider dispatcher. Every exit here is an advisory verdict — this never
    raises, because a lookup the customer did not ask to be blocked on must
    not be able to fail their checkout.
    """
    from yupay.modules.integrations.routes import _g2b_fulfiller_or_none

    game_code = await resolve_g2b_game_code(session, brand_id)
    if game_code is None:
        return PlayerCheckOut(status="error")

    redis = get_redis()
    key = _cache_key(game_code, player_id, server_id)
    cached = await _cached(key)
    if cached is not None:
        return cached

    fulfiller = _g2b_fulfiller_or_none()
    if fulfiller is None:
        return PlayerCheckOut(status="error")

    # Every database read this path needs is done. Ending the transaction here
    # returns the connection to the pool *before* the supplier round trip,
    # which is the difference between one slow supplier and an outage.
    #
    # The pool is twenty connections for the whole process, and a healthy G2B
    # check takes 830ms to 4.9s (measured on production). Held across the call,
    # four concurrent checks a second exhaust it — and the twenty-first request
    # to arrive is not another player check, it is somebody's checkout.
    #
    # `rollback` rather than `commit`: nothing here writes, and this must not
    # be the thing that flushes a caller's pending changes as a side effect.
    # The session stays usable — SQLAlchemy simply begins a new transaction if
    # anything asks it to.
    await session.rollback()

    breaker = _breaker_for_g2b()
    if await breaker.is_open():
        # Same answer the retries would have produced, ~15s sooner. The
        # storefront reads `error` as "couldn't check", never as a bad id, so
        # skipping the call costs the customer nothing but the wait.
        logger.info("player_check_short_circuited", game_code=game_code)
        return PlayerCheckOut(status="error")

    try:
        resp = await fulfiller._client().games_check_player(
            game_code=game_code, player_id=player_id, server_id=server_id, charname=None
        )
    except Exception as exc:  # noqa: BLE001 — advisory; degrade, never 500
        if _counts_against_supplier(exc):
            await breaker.record_failure()
        logger.warning(
            "player_check_failed",
            game_code=game_code,
            player_id_hash=hash_short(player_id),
            error=str(exc)[:200],
        )
        return PlayerCheckOut(status="error")

    await breaker.record_success()

    out = _map_response(resp)
    if _worth_caching(out):
        with contextlib.suppress(Exception):  # cache is best-effort
            await redis.set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    logger.info(
        "player_check",
        game_code=game_code,
        player_id_hash=hash_short(player_id),
        status=out.status,
    )
    return out
