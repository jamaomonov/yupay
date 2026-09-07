"""Public interface of the ``merchants`` module.

Other modules import from here, never from ``models`` or ``service``
directly — the same rule the rest of the codebase follows. Cabinet auth
lands in a later task and gets re-exported here when it arrives.

Two kinds of thing in this module are deliberately NOT re-exported, both for
the same reason: they bind to the ``/api/v1`` route stack, so a facade import
would close a cycle for any service-layer caller.

- the routers in ``admin_routes`` and in ``machine_routes`` (``api/v1`` and
  ``bootstrap`` respectively import them from those files);
- ``auth.merchant_auth``, the machine-API dependency, which takes its session
  from ``api.v1.deps.db_session`` so the endpoint behind it shares one
  transaction. Import it from ``merchants.auth`` directly.

The credential *lifecycle* (``create_api_key`` / ``list_api_keys`` /
``revoke_api_key``) and the wire format (``signing``) have no such binding
and are exported normally.

Where each name comes from is an implementation detail this facade exists to
hide — ``service`` (the account), ``credentials`` (its API keys), ``deposit``
(its money), ``admin``, ``orders``, ``price_list``, ``pricing``, ``signing``.
Importers see one surface and are unaffected when a file is split.
"""

from __future__ import annotations

from yupay.modules.merchants.admin import (
    bulk_set_markup,
    list_merchants_with_balances,
    set_brand_b2b,
    set_sku_b2b,
)
from yupay.modules.merchants.credentials import (
    IssuedApiKey,
    create_api_key,
    list_api_keys,
    revoke_api_key,
)
from yupay.modules.merchants.deposit import (
    DEPOSIT_CURRENCY,
    charge_deposit,
    credit_deposit,
    deposit_balance,
    list_deposit_transactions,
)
from yupay.modules.merchants.models import Merchant, MerchantApiKey, MerchantUser
from yupay.modules.merchants.order_status import read as read_order_status
from yupay.modules.merchants.orders import place as place_order
from yupay.modules.merchants.price_list import build as build_price_list
from yupay.modules.merchants.pricing import (
    effective_cost,
    merchant_markup_pct,
    merchant_price,
    violates_margin_floor,
)
from yupay.modules.merchants.service import create_merchant, set_status
from yupay.modules.merchants.signing import (
    body_digest,
    canonical_message,
    expected_signature,
    signature_matches,
)
from yupay.modules.merchants.transactions import build as build_transactions_page

__all__ = [
    "DEPOSIT_CURRENCY",
    "IssuedApiKey",
    "Merchant",
    "MerchantApiKey",
    "MerchantUser",
    "body_digest",
    "build_price_list",
    "build_transactions_page",
    "bulk_set_markup",
    "canonical_message",
    "charge_deposit",
    "create_api_key",
    "create_merchant",
    "credit_deposit",
    "deposit_balance",
    "effective_cost",
    "expected_signature",
    "list_api_keys",
    "list_deposit_transactions",
    "list_merchants_with_balances",
    "merchant_markup_pct",
    "merchant_price",
    "place_order",
    "read_order_status",
    "revoke_api_key",
    "set_brand_b2b",
    "set_sku_b2b",
    "set_status",
    "signature_matches",
    "violates_margin_floor",
]
