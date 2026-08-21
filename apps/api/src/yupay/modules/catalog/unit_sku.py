"""Helpers for identifying unit-priced SKUs (Telegram Stars, not Steam dollars).

A "unit SKU" is sold as an integer quantity of a named unit (e.g. 50 Stars) with
admin-configured bounds (:attr:`yupay.modules.catalog.models.Sku.min_qty` /
``max_qty``), as opposed to Steam's ``variable_amount`` path where the customer
types a free-form USD amount. The two are mutually exclusive by construction —
see :func:`is_unit_sku`.
"""

from __future__ import annotations

from yupay.core.errors import ValidationError

# Fallback ceiling on how many units an admin-configured SKU can require when
# no explicit ``max_qty`` is on file — kept far below ``UNIT_QTY_WIRE_MAX`` so
# a misconfigured SKU still can't be used to construct an oversized order.
DEFAULT_QTY_MAX: int = 100

# Hard ceiling accepted from the client on any unit-SKU quantity field,
# independent of the SKU's own ``max_qty`` — a last-resort guard against a
# malformed or malicious request regardless of what the admin configured.
UNIT_QTY_WIRE_MAX: int = 50_000


def is_unit_sku(sku: object) -> bool:
    """Sold as integer qty of a named unit (Telegram Stars), not Steam dollars.

    True only when ``variable_amount`` is falsy and ``amount_unit``,
    ``min_qty``, and ``max_qty`` are all set. Takes ``object`` (not ``Sku``)
    so it also accepts the ``SimpleNamespace`` fixtures used in unit tests
    and any other duck-typed row with the same attributes.
    """
    if getattr(sku, "variable_amount", False):
        return False
    return (
        getattr(sku, "amount_unit", None) is not None
        and getattr(sku, "min_qty", None) is not None
        and getattr(sku, "max_qty", None) is not None
    )


def assert_qty_allowed(sku: object, qty: int) -> None:
    """Enforce the *real* quantity ceiling behind the raised wire limit.

    ``OrderItemIn.qty`` accepts up to :data:`UNIT_QTY_WIRE_MAX` on the wire so
    a unit SKU (Telegram Stars) can be bought in bulk, but that wire limit is
    not a real limit for anything else — without this second gate, raising it
    would let a client buy ``qty=50000`` of a gift card or game top-up. A unit
    SKU is bounded by its own admin-configured ``min_qty``/``max_qty``; every
    other SKU is capped at :data:`DEFAULT_QTY_MAX`.

    Args:
        sku: The SKU (or duck-typed row) the line is buying.
        qty: The requested quantity, already wire-validated to
            ``[1, UNIT_QTY_WIRE_MAX]``.

    Raises:
        ValidationError: ``qty`` is outside the SKU's bounds (unit SKU) or
            exceeds :data:`DEFAULT_QTY_MAX` (everything else).
    """
    if is_unit_sku(sku):
        # ``is_unit_sku`` already guarantees both are set; the defaults are
        # unreachable sentinels, present only so this satisfies the same
        # duck-typed ``object`` signature as ``is_unit_sku`` without a bare
        # two-arg ``getattr`` (ruff B009).
        lo = int(getattr(sku, "min_qty", 0))
        hi = int(getattr(sku, "max_qty", 0))
        if qty < lo or qty > hi:
            raise ValidationError(
                "quantity is outside the allowed range",
                extra={"min_qty": lo, "max_qty": hi, "qty": qty},
            )
        return
    if qty > DEFAULT_QTY_MAX:
        raise ValidationError(
            "quantity exceeds the maximum for this product",
            extra={"max_qty": DEFAULT_QTY_MAX, "qty": qty},
        )


__all__ = ["DEFAULT_QTY_MAX", "UNIT_QTY_WIRE_MAX", "assert_qty_allowed", "is_unit_sku"]
