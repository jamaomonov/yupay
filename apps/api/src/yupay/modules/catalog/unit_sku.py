"""Helpers for identifying unit-priced SKUs (Telegram Stars, not Steam dollars).

A "unit SKU" is sold as an integer quantity of a named unit (e.g. 50 Stars) with
admin-configured bounds (:attr:`yupay.modules.catalog.models.Sku.min_qty` /
``max_qty``), as opposed to Steam's ``variable_amount`` path where the customer
types a free-form USD amount. The two are mutually exclusive by construction —
see :func:`is_unit_sku`.
"""

from __future__ import annotations

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


__all__ = ["DEFAULT_QTY_MAX", "UNIT_QTY_WIRE_MAX", "is_unit_sku"]
