"""Public interface of the ``merchants`` module.

Other modules import from here, never from ``models`` or ``service``
directly — the same rule the rest of the codebase follows. API-key issuance
and cabinet auth land in later tasks and get re-exported here as they arrive.
"""

from __future__ import annotations

from yupay.modules.merchants.admin import (
    bulk_set_markup,
    list_deposit_transactions,
    list_merchants_with_balances,
    set_brand_b2b,
    set_sku_b2b,
)
from yupay.modules.merchants.models import Merchant, MerchantApiKey, MerchantUser
from yupay.modules.merchants.pricing import (
    effective_cost,
    merchant_markup_pct,
    merchant_price,
    violates_margin_floor,
)
from yupay.modules.merchants.service import (
    DEPOSIT_CURRENCY,
    create_merchant,
    credit_deposit,
    deposit_balance,
    set_status,
)

__all__ = [
    "DEPOSIT_CURRENCY",
    "Merchant",
    "MerchantApiKey",
    "MerchantUser",
    "bulk_set_markup",
    "create_merchant",
    "credit_deposit",
    "deposit_balance",
    "effective_cost",
    "list_deposit_transactions",
    "list_merchants_with_balances",
    "merchant_markup_pct",
    "merchant_price",
    "set_brand_b2b",
    "set_sku_b2b",
    "set_status",
    "violates_margin_floor",
]
