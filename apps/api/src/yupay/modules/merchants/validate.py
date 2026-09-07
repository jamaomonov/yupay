"""The truthful player check a reseller may run before ordering (spec §9.1).

``POST /merchant/v1/validate/player``. Nothing here performs a check: the two
real providers — the G2B nickname lookup and the Waxpeer Steam-login check —
already live in :mod:`yupay.modules.integrations.player_check` behind one
advisory three-way result, a circuit breaker and a 300 s cache. This module
resolves *which* product a merchant's ``sku_id`` names, decides whether that
product has a checker at all, and projects the answer onto the machine API's
own wire contract.

## Never a fake approver

The rule the endpoint exists to obey, and the reason it is worth having at
all: **"we could not check" must never render as "valid"**. An upstream fault,
a rejected credential, a tripped breaker and an unconfigured supplier are the
same answer — ``status="error"`` — and a reseller who read a cheerful default
there would sell a top-up into a stranger's account. ``player_check`` already
degrades every fault to ``error`` rather than raising, which is exactly the
shape this surface needs; this module's job is to not undo it.

The second half of the same rule is the SKU with **no** configured checker.
That is not ``valid`` (it approves nothing), and it is not a 404 (which reads
as "no such SKU" and sends an integrator hunting an id that is fine). It is
its own answer, ``status="unsupported"``: permanent, and worth branching on,
because ``error`` is worth retrying and this never will be.

## What a merchant may check

Exactly what they can see in ``GET /merchant/v1/catalog``: ``visible_b2b`` on
both the brand and the SKU. A SKU withheld from B2B is not checkable, and the
refusal is the order path's own ``item_unavailable`` — one word for "you
cannot have this SKU", with the same ``reason`` vocabulary, rather than a
second one invented here.

The *rest* of ``load_orderable_sku``'s rules are deliberately **not** applied.
Stock, the active chain and the presence of a cost all move between a check
and an order, and this call is the step *before* the order — refusing to
verify a player id because the SKU is momentarily out of stock would answer a
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

from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import select

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

#: The fourth status, and the one this API adds to ``player_check``'s three:
#: this product has no checker, today or ever. Distinct from ``error`` because
#: that one is transient and this one is not.
STATUS_UNSUPPORTED: Final = "unsupported"


async def _checkable_product(db: AsyncSession, *, sku_id: str) -> tuple[str, list[dict[str, Any]]]:
    """Resolve a merchant-visible ``sku_id`` to its product and form schema.

    Columns rather than entities: ``Product`` configures ``lazy="selectin"``
    relationships for its translations, FAQs and whole SKU set, so loading it
    as an entity to read one JSONB column would drag the retail catalog along
    behind it.

    Args:
        db: Session. The caller owns the transaction.
        sku_id: The SKU's id, already known to be a well-formed UUID — the
            schema parses it, so this never reaches Postgres as
            ``uuid = 'whatever'``, which is a ``DataError`` and a 500 where a
            clean refusal belongs.

    Returns:
        ``(product_id, required_fields)`` for a SKU this merchant may see.

    Raises:
        NotFoundError: ``item_unavailable`` with a ``reason`` — ``unknown_sku``
            for an id that names nothing, ``not_b2b_visible`` for one they
            cannot see in ``/catalog``. The two are distinguished because a
            merchant can act on the difference: one is their bug, the other is
            a message for support.
    """
    row = (
        await db.execute(
            select(Product.id, Product.required_fields, Sku.visible_b2b, Brand.visible_b2b)
            .join(Product, Product.id == Sku.product_id)
            .join(Brand, Brand.id == Product.brand_id)
            .where(Sku.id == sku_id)
        )
    ).one_or_none()
    if row is None:
        raise quote.unavailable(sku_id, "unknown_sku")
    product_id, required_fields, sku_visible, brand_visible = row
    if not sku_visible or not brand_visible:
        raise quote.unavailable(sku_id, "not_b2b_visible")
    return str(product_id), list(required_fields or [])


async def check_player(
    db: AsyncSession, *, sku_id: str, player_id: str, server_id: str | None
) -> MerchantPlayerCheckOut:
    """Verify an end customer's player id against the SKU they will be sold.

    Advisory, and honest about it: every outcome the providers can produce is
    passed through unchanged, and the one outcome they cannot express — "this
    product has no checker" — gets its own status rather than borrowing
    ``valid``.

    No ``merchant`` parameter, and none is needed: B2B visibility is a
    property of the catalog row (``brand.visible_b2b AND sku.visible_b2b``),
    not of the caller, so every merchant sees the same checkable set. A
    per-merchant catalog would change that, and this is the function it would
    change.

    Note that :func:`player_check.check_player_for_product` ends the session's
    transaction before its supplier round trip, so that a slow supplier does
    not hold one of twenty pool connections. The only write in flight at that
    point is ``merchant_auth``'s throttled ``last_used_at`` stamp, which is
    explicitly best-effort and is re-attempted by the next request.

    Args:
        db: Session. The caller owns the transaction.
        sku_id: The SKU the merchant intends to order, from ``/catalog``.
        player_id: The end customer's identifier — a game player id, or a
            Steam login for a Steam top-up. Never logged, never in a URL.
        server_id: The game server / zone, where the game asks for one.

    Returns:
        ``valid`` (the id resolved; ``name`` carries the nickname where the
        provider gives one), ``invalid`` (the provider answered and the id
        does not exist), ``error`` (we could not check — retry later), or
        ``unsupported`` (this SKU has no checker; order without one).

    Raises:
        NotFoundError: ``item_unavailable`` — see :func:`_checkable_product`.
    """
    product_id, required_fields = await _checkable_product(db, sku_id=sku_id)
    if not player_check.product_is_checkable(required_fields):
        return MerchantPlayerCheckOut(status=STATUS_UNSUPPORTED)
    result = await player_check.check_player_for_product(
        db, product_id=product_id, player_id=player_id, server_id=server_id
    )
    return MerchantPlayerCheckOut(status=result.status, name=result.name)


__all__ = ["RATE_BUCKET", "STATUS_UNSUPPORTED", "check_player"]
