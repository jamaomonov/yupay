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

The same binding is why ``orders.service``'s status-change seam reaches for
``merchants.webhooks`` as a submodule rather than through here: this facade
imports routers, and ``merchants.orders`` imports ``orders.service``, so a
facade import from inside that cycle would not resolve. The webhook producer
is exported below all the same, for every caller that is not in the cycle —
under ``enqueue_`` names, never under the seam's own
``on_order_status_changed``. Two functions taking ``(db, order)`` under one
name, one of which also nudges retail, is an autocomplete away from silently
turning the storefront's live updates off.

The credential *lifecycle* (``create_api_key`` / ``list_api_keys`` /
``revoke_api_key``) and the wire format (``signing``) have no such binding
and are exported normally.

Where each name comes from is an implementation detail this facade exists to
hide — ``service`` (the account), ``credentials`` (its API keys), ``deposit``
(its money), ``admin`` (the catalog B2B knobs and the outgoing-webhook
configuration), ``webhooks`` (the outbox producer), ``webhook_delivery`` (the
drain ``apps/worker`` runs, exported beside the channel constant it wakes on
so the queue cannot be spelled twice), ``orders``, ``price_list``,
``pricing``, ``signing``, ``validate`` (the advisory player check).
Importers see one surface and are unaffected when a file is split.
"""

from __future__ import annotations

from yupay.modules.merchants.admin import (
    ConfiguredWebhook,
    bulk_set_markup,
    disable_webhook,
    get_webhook,
    list_merchants_with_balances,
    rotate_webhook_secret,
    set_brand_b2b,
    set_sku_b2b,
    set_webhook,
    validate_webhook_url,
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
    order_reference_of,
)
from yupay.modules.merchants.models import (
    Merchant,
    MerchantApiKey,
    MerchantUser,
    MerchantWebhook,
    MerchantWebhookDelivery,
)
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

# Renamed on the way out, like ``enqueue`` below and for the same reason: at
# this facade's altitude a bare ``RATE_BUCKET`` sits beside ``auth``'s and a
# bare ``check_player`` beside the storefront's, and neither reader could tell
# which is which.
from yupay.modules.merchants.validate import (
    RATE_BUCKET as VALIDATE_RATE_BUCKET,
)
from yupay.modules.merchants.validate import (
    charge_merchant_quota as charge_validate_quota,
)
from yupay.modules.merchants.validate import (
    check_player as check_player_for_brand,
)
from yupay.modules.merchants.webhook_delivery import drain_pending_deliveries
from yupay.modules.merchants.webhooks import (
    EVENT_BALANCE_CREDITED,
    EVENT_ORDER_STATUS_CHANGED,
    EVENT_TYPES,
    WEBHOOK_QUEUE_CHANNEL,
    enqueue_balance_credited,
    enqueue_order_status_changed,
)
from yupay.modules.merchants.webhooks import (
    enqueue as enqueue_webhook_event,
)

__all__ = [
    "DEPOSIT_CURRENCY",
    "EVENT_BALANCE_CREDITED",
    "EVENT_ORDER_STATUS_CHANGED",
    "EVENT_TYPES",
    "VALIDATE_RATE_BUCKET",
    "WEBHOOK_QUEUE_CHANNEL",
    "ConfiguredWebhook",
    "IssuedApiKey",
    "Merchant",
    "MerchantApiKey",
    "MerchantUser",
    "MerchantWebhook",
    "MerchantWebhookDelivery",
    "body_digest",
    "build_price_list",
    "build_transactions_page",
    "bulk_set_markup",
    "canonical_message",
    "charge_deposit",
    "charge_validate_quota",
    "check_player_for_brand",
    "create_api_key",
    "create_merchant",
    "credit_deposit",
    "deposit_balance",
    "disable_webhook",
    "drain_pending_deliveries",
    "effective_cost",
    "enqueue_balance_credited",
    "enqueue_order_status_changed",
    "enqueue_webhook_event",
    "expected_signature",
    "get_webhook",
    "list_api_keys",
    "list_deposit_transactions",
    "list_merchants_with_balances",
    "merchant_markup_pct",
    "merchant_price",
    "order_reference_of",
    "place_order",
    "read_order_status",
    "revoke_api_key",
    "rotate_webhook_secret",
    "set_brand_b2b",
    "set_sku_b2b",
    "set_status",
    "set_webhook",
    "signature_matches",
    "validate_webhook_url",
    "violates_margin_floor",
]
