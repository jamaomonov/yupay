"""Public interface of the ``affiliate`` module.

Other modules and the scheduler import from here, never from ``accrual`` or
``ledger`` directly — the same rule the rest of the codebase follows, and what
lets the internals move without a cross-module edit.

Unlike most module facades here, this one imports no router: the affiliate
routes land in a later step, and until then a scheduler process that imports
this pays nothing for it.
"""

from __future__ import annotations

from yupay.modules.affiliate.accrual import (
    accrue_commissions,
    mature_commissions,
    void_commission,
)
from yupay.modules.affiliate.discount import (
    DiscountRejection,
    ResolvedDiscount,
    discount_amount,
    distribute_discount_usd,
    resolve_code,
)

__all__ = [
    "DiscountRejection",
    "ResolvedDiscount",
    "accrue_commissions",
    "discount_amount",
    "distribute_discount_usd",
    "mature_commissions",
    "resolve_code",
    "void_commission",
]
