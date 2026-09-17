"""NOVA as a second opinion for the player check.

The primary check (G2B for a game, Waxpeer for a Steam login) answers
``valid`` / ``invalid`` / ``error``. This module is consulted for exactly one
of those: **``error``**, which means we have no verdict at all — G2B rate-limited
us, refused, or could not be reached. ``valid`` and ``invalid`` are answers, and
an answer is never second-guessed.

**It can say ``valid`` or ``error``. It never says ``invalid``.** Three reasons,
in order of weight:

1. It only runs when there is no primary verdict, so its ``invalid`` would be
   the sole basis for blocking a paying customer (ADR-0031: ``invalid`` is the
   one verdict that blocks Pay).
2. Their MLBB validate category is one namespace for a catalogue we split into
   two brands, and the ``region`` word it returns is of unproven meaning.
3. It is how this codebase already treats an answer it cannot read:
   ``player_check._map_response`` returns ``error``, not ``invalid``, for a
   G2B verdict outside the two it recognises — precisely so the check never
   becomes a fake rejecter.

The cost is that a customer who mistypes during a G2B outage is told "could not
check" instead of "wrong id" — which is what they are told today. The gain, a
confirmed nickname while G2B is down, is kept in full.

**Their validate ids are not their top-up ids** (``mobile_legends`` validates,
``mobile_legends_ru`` sells) and their validate field key for a server is
``zone_id``, while the order endpoint wants ``server_id``. Both are easy to
cross and neither fails loudly.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yupay.core.config import get_settings
from yupay.core.logging import get_logger, hash_short
from yupay.core.redis import get_redis
from yupay.modules.fulfillment.suppliers.nova_client import NovaError
from yupay.modules.integrations.breaker import SupplierBreaker
from yupay.modules.integrations.schemas import PlayerCheckOut

if TYPE_CHECKING:
    from yupay.modules.fulfillment.suppliers.nova_client import NovaValidation

logger = get_logger("yupay.integrations.player_check_nova")

#: Same window and thresholds as the G2B breaker: three consecutive failures
#: catch a real outage within a few customers, and 30s is short enough that a
#: blip costs almost nobody a check.
_BREAKER_THRESHOLD = 3
_BREAKER_COOLDOWN_SECONDS = 30


@dataclass(frozen=True)
class NovaValidateTarget:
    """How one of our brands maps onto NOVA's validate namespace.

    Attributes:
        category_id: Their id in the **validate** namespace. Never a top-up
            ``category_id``; nothing in their API links the two.
        region_word: A lowercased substring their ``region`` must contain for
            this brand, or ``None`` when the game has one region worldwide. A
            brand that expects a word and gets nothing back fails the guard:
            the guard wants positive evidence, not the absence of contrary
            evidence.
    """

    category_id: str
    region_word: str | None


#: The brands NOVA may be asked about. A code table rather than a database
#: mapping on purpose: validation is brand-scoped where mappings are SKU-scoped,
#: NOVA validates five games in total, and adding a brand here should cost a
#: review of what its region word means rather than a row somebody can add in
#: the admin without thinking about it.
#:
#: ``mobile-legends`` (global) is deliberately absent. Their single
#: ``mobile_legends`` category has only ever been observed answering for a
#: Russian account, and a brand we cannot tell apart gets no fallback rather
#: than a guess. See the design doc's open questions for the one probe that
#: settles it.
NOVA_VALIDATE: dict[str, NovaValidateTarget] = {
    "mobile-legends-ru": NovaValidateTarget("mobile_legends", "russia"),
    "pubg-mobile": NovaValidateTarget("pubg_mobile", None),
    "free-fire": NovaValidateTarget("free_fire", None),
    "magic-chess-gogo": NovaValidateTarget("magic_chess_gogo_global", None),
    "magic-chess-gogo-ru": NovaValidateTarget("magic_chess_gogo_ru", None),
}


def _breaker() -> SupplierBreaker:
    """The circuit guarding NOVA's advisory calls.

    Separate from G2B's: this path is reached *because* G2B is unwell, so one
    supplier's outage must not open the other's circuit. Shared between the
    brand and the Steam entry points below — both are the same supplier
    answering the same kind of advisory question.
    """
    return SupplierBreaker(
        "nova:player_check",
        threshold=_BREAKER_THRESHOLD,
        cooldown_seconds=_BREAKER_COOLDOWN_SECONDS,
    )


def _counts_against_supplier(exc: BaseException) -> bool:
    """Whether ``exc`` says something about NOVA's *health*.

    The primary check asks the same question fifty lines away, for the same
    reason (``player_check._counts_against_supplier``): the circuit is shared
    across the supplier, so counting a refusal that is really about *our
    request* lets one bad input silence the check for every brand.

    Here the exposure is larger than it is for G2B, because the client raises
    on everything: a ``422`` is their "could not confirm this id", which is
    what a customer mistyping their player id looks like, and a ``404`` is a
    ``category_id`` typo in :data:`NOVA_VALIDATE`. Three of either would open
    the circuit for thirty seconds — during a G2B outage, which is the only
    time this code runs at all.

    So: a transport failure counts (nothing was decided, and the client has
    already spent its patience), a 5xx counts (their side is unwell), 401 or
    403 count because a rejected key or a disabled subscription will not fix
    itself and every further call is a wasted round trip on a customer's
    spinner, and 429 counts because backing off is the entire point of a rate
    limit — this whole module exists because the primary hit one. Everything
    else — 400, 404, 409, 422 — is about what we sent.
    """
    if isinstance(exc, NovaError):
        return exc.status >= 500 or exc.status in (401, 403, 429)
    return True


def _redacted(text: str, *ours: str | None) -> str:
    """Their message with anything we submitted taken back out.

    Their error string is theirs, not ours: an API that answers "player
    51234567 not found" would put a customer's id in our logs (§9). We know
    exactly what we sent, so the redaction is exact. The fulfiller does the
    same thing for the same reason — see ``suppliers/nova.py``'s
    ``_without_our_inputs`` — but the two live on opposite sides of a module
    boundary and neither is worth a shared home yet.

    Values shorter than three characters are left alone: a server id like
    ``"1"`` would blank half the sentence.
    """
    for value in ours:
        if value and len(value) >= 3:
            text = text.replace(value, "…")
    return text


def _cache_key(category_id: str, player_id: str, server_id: str | None) -> str:
    """Redis key for a cached NOVA verdict.

    Its own namespace, so a NOVA answer can never be served as a G2B one, and
    the id is hashed for the same PII reason (§9) as the primary's key.
    """
    return f"playercheck:nova:{category_id}:{server_id or '-'}:{hash_short(player_id)}"


def _steam_cache_key(steam_login: str) -> str:
    """Redis key for a cached NOVA Steam-login verdict. Own namespace, hashed."""
    return f"playercheck:nova:steam:{hash_short(steam_login)}"


def _resolve_target(brand_slug: str | None) -> NovaValidateTarget | None:
    """The validate target for a brand, or ``None`` when the fallback must not
    run at all — the kill switch is off, or the brand is outside
    :data:`NOVA_VALIDATE`. Split out of :func:`fallback_for_brand` only to
    keep that function's early returns under the linter's ceiling; the two
    checks are one decision, not two.
    """
    if not get_settings().nova_player_check_enabled:
        return None
    return NOVA_VALIDATE.get(brand_slug or "")


def _verdict(answer: NovaValidation, target: NovaValidateTarget) -> PlayerCheckOut:
    """Turn one NOVA answer into an advisory verdict.

    A negative becomes ``error``, not ``invalid``: see the module docstring.
    A positive whose region does not match the brand becomes ``error`` too —
    the same rule, applied to the one case where their answer may be about a
    different game client than the customer is buying for.
    """
    if not answer.valid:
        return PlayerCheckOut(status="error")
    if target.region_word:
        region = (answer.region or "").lower()
        if target.region_word not in region:
            logger.warning(
                "player_check_fallback_region_mismatch",
                provider="nova",
                category_id=target.category_id,
                expected=target.region_word,
                region=region[:32] or "(none)",
                hint="NOVA validated the id for a different region than this brand "
                "sells; answering `error` rather than confirming the wrong game",
            )
            return PlayerCheckOut(status="error")
    return PlayerCheckOut(status="valid", name=answer.player_name)


async def fallback_for_brand(
    *, brand_slug: str | None, player_id: str, server_id: str | None
) -> PlayerCheckOut:
    """Ask NOVA about a player id. Returns ``valid`` or ``error``, never ``invalid``.

    Args:
        brand_slug: Our brand. A slug absent from :data:`NOVA_VALIDATE` gets no
            call at all.
        player_id: Never logged, only hashed.
        server_id: The sibling server/zone value, sent as their ``zone_id``.
    """
    from yupay.modules.integrations.player_check import _CACHE_TTL_SECONDS, _cached, _worth_caching
    from yupay.modules.integrations.routes import _nova_fulfiller_or_none

    target = _resolve_target(brand_slug)
    if target is None:
        return PlayerCheckOut(status="error")
    settings = get_settings()

    key = _cache_key(target.category_id, player_id, server_id)
    cached = await _cached(key)
    if cached is not None:
        return cached

    fulfiller = _nova_fulfiller_or_none()
    if fulfiller is None:
        return PlayerCheckOut(status="error")

    breaker = _breaker()
    if await breaker.is_open():
        logger.info(
            "player_check_fallback_short_circuited", provider="nova", category_id=target.category_id
        )
        return PlayerCheckOut(status="error")

    # Their validate endpoint names the server `zone_id`; their order endpoint
    # names it `server_id`. Crossing the two is silent.
    fields: dict[str, str] = {"player_id": player_id}
    if server_id:
        fields["zone_id"] = server_id

    try:
        answer = await fulfiller._client().validate_id(
            category_id=target.category_id,
            fields=fields,
            timeout=settings.nova_check_timeout_seconds,
        )
    except Exception as exc:  # noqa: BLE001 — advisory; degrade, never 500
        if _counts_against_supplier(exc):
            await breaker.record_failure()
        logger.warning(
            "player_check_failed",
            provider="nova",
            category_id=target.category_id,
            player_id_hash=hash_short(player_id),
            error=_redacted(str(exc), player_id, server_id)[:200],
        )
        return PlayerCheckOut(status="error")

    await breaker.record_success()
    out = _verdict(answer, target)
    if _worth_caching(out):
        with contextlib.suppress(Exception):  # cache is best-effort
            await get_redis().set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    logger.info(
        "player_check",
        provider="nova",
        category_id=target.category_id,
        player_id_hash=hash_short(player_id),
        status=out.status,
    )
    return out


async def fallback_for_steam(*, steam_login: str) -> PlayerCheckOut:
    """Ask NOVA whether it can refill a Steam login. Returns ``valid`` or
    ``error``, never ``invalid``.

    ``can_refill: false`` is NOVA saying *they* cannot refill that account —
    a weaker statement than "no such login", and not one a customer may be
    shown as a rejection.

    Args:
        steam_login: Never logged, only hashed.
    """
    from yupay.modules.integrations.player_check import _CACHE_TTL_SECONDS, _cached, _worth_caching
    from yupay.modules.integrations.routes import _nova_fulfiller_or_none

    settings = get_settings()
    if not settings.nova_player_check_enabled:
        return PlayerCheckOut(status="error")

    key = _steam_cache_key(steam_login)
    cached = await _cached(key)
    if cached is not None:
        return cached

    fulfiller = _nova_fulfiller_or_none()
    if fulfiller is None:
        return PlayerCheckOut(status="error")

    breaker = _breaker()
    if await breaker.is_open():
        logger.info("player_check_fallback_short_circuited", provider="nova", category_id="steam")
        return PlayerCheckOut(status="error")

    try:
        can_refill = await fulfiller._client().check_steam_login(
            steam_login, timeout=settings.nova_check_timeout_seconds
        )
    except Exception as exc:  # noqa: BLE001 — advisory; degrade, never 500
        if _counts_against_supplier(exc):
            await breaker.record_failure()
        logger.warning(
            "player_check_failed",
            provider="nova",
            category_id="steam",
            player_id_hash=hash_short(steam_login),
            error=_redacted(str(exc), steam_login)[:200],
        )
        return PlayerCheckOut(status="error")

    await breaker.record_success()
    out = PlayerCheckOut(status="valid") if can_refill else PlayerCheckOut(status="error")
    if _worth_caching(out):
        with contextlib.suppress(Exception):  # cache is best-effort
            await get_redis().set(key, out.model_dump_json(), ex=_CACHE_TTL_SECONDS)
    logger.info(
        "player_check",
        provider="nova",
        category_id="steam",
        player_id_hash=hash_short(steam_login),
        status=out.status,
    )
    return out


__all__ = ["NOVA_VALIDATE", "NovaValidateTarget", "fallback_for_brand", "fallback_for_steam"]
