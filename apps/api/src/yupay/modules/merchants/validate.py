"""The truthful player check a reseller may run before ordering (spec §9.1).

``POST /merchant/v1/validate/player``. Nothing here performs a check: the two
real providers — the G2B nickname lookup and the Waxpeer Steam-login check —
already live in :mod:`yupay.modules.integrations.player_check` behind one
advisory three-way result, a circuit breaker and a 300 s cache. This module
resolves *which* brand a merchant's ``brand`` slug names, decides whether that
brand has a checker at all, and projects the answer onto the machine API's
own wire contract.

## Never a fake approver

The rule the endpoint exists to obey, and the reason it is worth having at
all: **"we could not check" must never render as "valid"**. An upstream fault,
a rejected credential, a tripped breaker and an unconfigured supplier are the
same answer — ``status="error"`` — and a reseller who read a cheerful default
there would sell a top-up into a stranger's account. ``player_check`` already
degrades every fault to ``error`` rather than raising, which is exactly the
shape this surface needs; this module's job is to not undo it.

The second half of the same rule is the brand with **no** configured checker.
That is not ``valid`` (it approves nothing), and it is not a 404 (which reads
as "no such brand" and sends an integrator hunting an id that is fine). It is
its own answer, ``status="unsupported"``: permanent, and worth branching on,
because ``error`` is worth retrying and this never will be.

## What a merchant may check

Exactly what they can see in ``GET /merchant/v1/catalog``: ``visible_b2b`` on
both the brand and at least one of its SKUs. A brand withheld from B2B is not
checkable, and the refusal is the order path's own ``item_unavailable`` — one
word for "you cannot have this brand", with the same ``reason`` vocabulary,
rather than a second one invented here.

The *rest* of ``load_orderable_sku``'s rules are deliberately **not** applied.
Stock, the active chain and the presence of a cost all move between a check
and an order, and this call is the step *before* the order — refusing to
verify a player id because a SKU is momentarily out of stock would answer a
question the merchant did not ask. Visibility is the only permanent,
per-merchant-surface property in that list, and it is the only one that
governs enumeration.

## PII

``player_id`` is the reseller's **end customer's** identifier (a game player
id, or a Steam login). Transit-only, exactly like ``fulfillment_data`` on an
order: never in a URL — which is why this is a ``POST`` although it writes
nothing, the edge access log records query strings verbatim — and never in a
log line. Nothing here logs it; ``player_check`` logs only ``hash_short`` of
it (AGENTS.md §9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from sqlalchemy import select

from yupay.core.config import get_settings
from yupay.core.errors import RateLimitedError
from yupay.modules.auth.ip_guard import hit_counter
from yupay.modules.catalog.models import Brand, Product, Sku
from yupay.modules.integrations import player_check
from yupay.modules.merchants import quote
from yupay.modules.merchants.machine_schemas import MerchantPlayerCheckOut

if TYPE_CHECKING:  # pragma: no cover -- type hints only
    from sqlalchemy.ext.asyncio import AsyncSession

#: The ``auth_ip_guard_bucket_max`` bucket this endpoint charges, on top of
#: the prefix-wide ``merchants.auth.RATE_BUCKET`` every request already pays.
#: Its own bucket because it is the one endpoint here that spends a *supplier's*
#: quota rather than ours (spec §12: "stricter on ``validate/*``").
RATE_BUCKET: Final = "merchant-validate"

#: Redis key for the per-merchant axis of the same guard. Catalogued in
#: ``docs/architecture/cache-keys.md``. See :func:`charge_merchant_quota` for
#: why an address counter alone is the wrong shape for this limit.
_RATE_KEY: Final = "merchants:validate:{merchant_id}"

#: The fourth status, and the one this API adds to ``player_check``'s three:
#: this product has no checker, today or ever. Distinct from ``error`` because
#: that one is transient and this one is not.
STATUS_UNSUPPORTED: Final = "unsupported"


async def charge_merchant_quota(merchant_id: str) -> None:
    """Count one check against this merchant's share of the supplier quota.

    The second axis of this endpoint's guard, and the one that matches what is
    being rationed. :data:`RATE_BUCKET` counts **addresses**; the resource is a
    supplier's per-account quota, which a reseller spends per *merchant* and
    not per egress node — so with the address counter alone a six-node NAT pool
    held six budgets, and the ceiling that actually bound was
    ``merchant_api_key_rate_max`` (600), five times the number the bucket
    advertises. The address counter stays, because it is charged before we know
    who is calling and is what an unauthenticated flood meets.

    Keyed on ``merchant_id``, not ``key_id`` — deliberately unlike
    ``merchant_auth``'s per-key counter. A fair share of *our* request capacity
    may briefly double during a key rotation and nobody is worse off; a
    supplier's quota is a real external budget, and rotating a key must not
    double a merchant's claim on it.

    Best-effort, like every counter in this codebase: ``hit_counter`` fails
    open on Redis trouble. That is the same outage that empties the 300 s
    result cache and the supplier breaker, so a Redis failure removes all three
    protections at once and the supplier's own limiter is what remains. Known
    and accepted; the module README says so rather than implying a guarantee
    that does not hold.

    Args:
        merchant_id: The authenticated merchant's id.

    Raises:
        RateLimitedError: 429 with ``Retry-After``, in the prefix's RFC 7807
            shape.
    """
    settings = get_settings()
    window = settings.auth_ip_guard_window_seconds
    if await hit_counter(
        _RATE_KEY.format(merchant_id=merchant_id),
        limit=settings.merchant_validate_rate_max,
        window=window,
    ):
        raise RateLimitedError(
            "too many player checks for this merchant, slow down", retry_after=window
        )


async def _checkable_brand(db: AsyncSession, *, brand_slug: str) -> str:
    """Resolve a merchant-visible brand slug to its id.

    The rule is exactly ``/catalog``'s — ``price_list.py``'s catalog query
    filters on ``Brand.visible_b2b AND Sku.visible_b2b`` and nothing else
    (``price_list.py:194-196``). The active chain (brand, product, SKU) is
    deliberately **not** applied here either, for the same reason
    ``price_list.py`` does not apply it (``price_list.py:224-232``): active is
    a transient state that moves between a merchant's poll and their order, so
    filtering on it here would 404 a brand ``/catalog`` still lists as
    checkable. A brand withheld from B2B (or visible with no B2B-visible SKU)
    is not checkable, so this endpoint cannot be used to enumerate what
    ``/catalog`` hides — but it also cannot be *stricter* than what
    ``/catalog`` shows.

    One statement, not two: the visible-SKU test rides along as a correlated
    ``EXISTS`` on the brand row rather than a second round trip — the same
    reason the SKU-scoped lookup this replaces read brand and SKU visibility
    off one join (``test_the_check_does_not_fan_out_over_the_catalog`` pins
    the total).

    Raises:
        NotFoundError: ``item_unavailable`` with ``reason`` — ``unknown_brand``
            for a slug that names nothing, ``not_b2b_visible`` for one the
            merchant cannot see (withheld itself, or with no B2B-visible SKU).
    """
    has_visible_sku = (
        select(Sku.id)
        .join(Product, Product.id == Sku.product_id)
        .where(Product.brand_id == Brand.id, Sku.visible_b2b.is_(True))
        .exists()
    )
    row = (
        await db.execute(
            select(Brand.id, Brand.visible_b2b, has_visible_sku).where(Brand.slug == brand_slug)
        )
    ).one_or_none()
    if row is None:
        raise quote.unavailable_brand(brand_slug, "unknown_brand")
    # SQLAlchemy's typed ``select()`` overloads do not infer past a correlated
    # ``Exists`` argument, so the row comes back untyped; the three-column
    # shape is fixed by the ``select()`` above.
    brand_id, visible, sku_visible = cast("tuple[str, bool, bool]", row)
    if not visible or not sku_visible:
        raise quote.unavailable_brand(brand_slug, "not_b2b_visible")
    return brand_id


async def check_player(
    db: AsyncSession, *, brand: str, player_id: str, server_id: str | None
) -> MerchantPlayerCheckOut:
    """Advisory player check for a reseller, scoped to a brand they can see.

    Returns ``unsupported`` when no product of the brand declares a check — the
    reseller orders without one — and otherwise the provider's own verdict
    (``valid`` / ``invalid``) or ``error`` when we could not check.
    """
    brand_id = await _checkable_brand(db, brand_slug=brand)
    if await player_check.brand_check_field(db, brand_id) is None:
        return MerchantPlayerCheckOut(status=STATUS_UNSUPPORTED)
    result = await player_check.check_player_for_brand_id(
        db, brand_id=brand_id, player_id=player_id, server_id=server_id
    )
    return MerchantPlayerCheckOut(status=result.status, name=result.name)


__all__ = ["RATE_BUCKET", "STATUS_UNSUPPORTED", "charge_merchant_quota", "check_player"]
