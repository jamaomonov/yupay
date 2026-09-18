"""Pydantic DTOs for the sourcing admin HTTP surface."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["auto", "force_inventory", "force_supplier", "manual"]


class SourcingRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Mode
    supplier_slug: str | None = Field(default=None, min_length=2, max_length=32)


class SourcingRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sku_id: str
    # ``sku_sourcing_rules`` has no ORM relationship to ``Sku`` — the route
    # resolves this separately (see ``service.sku_codes_for``) so the admin
    # UI can show the human SKU code instead of a raw UUID.
    sku_code: str
    mode: Mode
    supplier_slug: str | None
    updated_by: str | None
    updated_at: datetime


class SourcingRuleListOut(BaseModel):
    items: list[SourcingRuleOut]


class SourcingDecisionOut(BaseModel):
    primary: str
    fallback: str | None
    strict: bool
    rule_present: bool


class SourcingBrandSupplierOut(BaseModel):
    """One candidate supplier's mapping + latest cost for a single SKU.

    The candidate set the brand-overview endpoint reports is
    ``MAPPING_REQUIRED_SUPPLIERS`` (g2b, gengine, nova) *union* every
    supplier that actually has a mapping row among the brand's SKUs *union*
    every supplier named by a ``force_supplier`` rule among those SKUs
    (``integrations.models``, ADR-0019). The fixed half means a supplier
    the SKU has never been mapped to still gets a row here, with
    ``has_active_mapping=False`` and no cost, so an operator comparing
    suppliers can see it as a switch target rather than it silently being
    absent. The two union halves mean a supplier outside that fixed set
    (e.g. waxpeer) that won the live route — either via a mapping
    (``_pick_auto_mapping_slug``) or via an explicit ``force_supplier`` rule
    (``_resolve_explicit_rule``, which accepts any slug, mapping or not) —
    still appears here too.

    For a **real supplier** (a slug the fulfilment ``REGISTRY`` actually
    dispatches to), this list is guaranteed to contain whatever
    ``SourcingBrandSkuOut.primary`` names — that is the invariant it exists
    to uphold, so the reported route never names a supplier absent from its
    own comparison. ``primary`` can still be ``"supplier:manual"`` on a
    ``top_up`` SKU with no mapping and no rule (``_auto_decision``'s
    no-mapping fallback) or an explicit ``mode="manual"`` rule — ``manual``
    is not a supplier, has no ``SkuSupplierMapping``/``SupplierPriceHistory``
    rows, and is never a candidate here; the UI renders it as "no automated
    route" rather than looking it up in this list. Same for ``"invalid"`` —
    ``brand_overview.get_brand_overview``'s per-row fallback for a malformed
    ``force_supplier`` rule with no ``supplier_slug`` — which names no
    supplier at all. Sorted alphabetically for a stable order.

    ``latest_cost_usdt`` is a string (mirrors
    ``integrations.schemas.PricePointOut.cost_usdt``, the other DTO that
    surfaces a ``supplier_price_history`` row) rather than the ``Decimal``
    used for the SKU's own ``price_usd``/``cost_usdt`` below — those two
    are ``Sku`` columns exposed the way ``catalog.admin_schemas.AdminSkuOut``
    already exposes them.

    ``cost_source`` says where ``latest_cost_usdt`` came from, because
    ``supplier_price_history`` records a price *change*, not a current
    state — a supplier whose cost has simply never moved since the mapping
    was created has zero history rows even though its price is known and
    live on ``Sku.cost_usdt`` (every Free Fire SKU in production is exactly
    this: zero g2b history rows, g2b's price sitting in ``cost_usdt`` to
    the cent). Rendering that as "not captured" would be false for the one
    supplier the SKU is actually buying from:

    - ``"history"`` — a ``supplier_price_history`` row exists for this
      (sku, supplier); ``latest_cost_usdt``/``captured_at`` are that row's.
    - ``"current"`` — no history row, but this supplier is the one the SKU
      routes to (``integrations.cost_refresh.is_routed_supplier`` — the
      same routed-supplier test ``cost_refresh`` itself uses to decide who
      may write ``Sku.cost_usdt``, ADR-0083 Decision 1), price collection
      actually reaches this supplier
      (``integrations.cost_refresh.supports_price_collection`` — g2b/nova
      only, the same dispatch ``refresh_sku_cost_for_mapping`` uses), and
      ``Sku.cost_usdt`` is not ``None``. All three must hold: a SKU
      force-routed to a supplier price collection never queries (gengine,
      waxpeer, ...) would otherwise report a *previous* routed supplier's
      leftover number as this one's "current" price. When they do,
      ``latest_cost_usdt`` is ``Sku.cost_usdt`` and ``captured_at`` is
      ``None`` (it is not a point-in-time capture).
    - ``None`` — none of the above: this supplier's price is genuinely
      unknown to us, or not honestly attributable to it. ``latest_cost_usdt``
      stays ``None``, same as before this field existed.
    """

    supplier_slug: str
    has_active_mapping: bool
    latest_cost_usdt: str | None
    captured_at: datetime | None
    cost_source: Literal["history", "current"] | None


class SourcingBrandSkuOut(BaseModel):
    """One active SKU's sourcing picture for the brand-overview screen.

    ``fallback`` mirrors ``SourcingDecisionOut.fallback`` / ``Decision.
    fallback`` — it is what carries the real cost owner for a voucher SKU
    routed ``primary="inventory"``: ``integrations.cost_refresh.
    is_routed_supplier`` treats ``primary == "inventory" and fallback ==
    "supplier:<slug>"`` as "<slug> owns this SKU's ``Sku.cost_usdt``"
    (ADR-0083 Decision 1). Without it here, this screen — built to show who
    owns a SKU's cost — could not show that for any voucher SKU.

    ``product_kind`` exists so the brand-overview screen can stop *offering*
    an action the backend will refuse anyway: ``sourcing.service.set_rule``
    rejects ``mode="force_inventory"`` on a ``top_up`` SKU (Task 3's guard —
    a top_up SKU has nothing to deliver from the code warehouse), but this
    row previously carried no kind signal at all, and ``primary``/
    ``fallback`` cannot substitute for one. Under ``mode="auto"`` a top_up
    SKU never reports ``primary == "inventory"`` (``_auto_decision`` only
    ever gives it ``supplier:<slug>`` or ``supplier:manual``) — so
    ``primary == "inventory"`` on a top_up row can only mean a pre-existing
    bad rule, not something the UI can use to infer a SKU is a voucher. The
    backend rejection in ``set_rule`` stays the real guard; this field only
    lets the per-row "склад" control and the bulk "Только склад" mode
    disable themselves for a ``top_up`` row instead of round-tripping a 422.
    """

    sku_id: str
    sku_code: str
    denomination: str | None
    product_slug: str
    product_kind: str
    price_usd: Decimal
    cost_usdt: Decimal | None
    primary: str
    fallback: str | None
    rule_present: bool
    suppliers: list[SourcingBrandSupplierOut]


class SourcingBrandOverviewOut(BaseModel):
    items: list[SourcingBrandSkuOut]


#: Per-request cap on ``SourcingBulkRuleIn.sku_ids`` — one request cannot walk
#: the whole catalogue. Enforced in ``bulk_rules.bulk_set_rules`` (an explicit
#: ``ValidationError`` with a structured ``extra``, matching
#: ``inventory.service.MAX_BULK``) rather than as a ``Field`` constraint here,
#: so an over-cap request gets the same RFC 7807 shape as every other business
#: rejection in this module instead of FastAPI's generic body-validation 422.
MAX_BULK_SKU_IDS = 100


class SourcingBulkRuleIn(BaseModel):
    """Switch many SKUs to one sourcing decision in a single request."""

    model_config = ConfigDict(extra="forbid")

    sku_ids: list[str] = Field(min_length=1)
    mode: Mode
    supplier_slug: str | None = Field(default=None, min_length=2, max_length=32)


class SourcingBulkRuleResultOut(BaseModel):
    """One SKU's outcome inside a bulk write — success or a named failure."""

    sku_id: str
    ok: bool
    error: str | None = None


class SourcingBulkRuleOut(BaseModel):
    items: list[SourcingBulkRuleResultOut]


__all__ = [
    "MAX_BULK_SKU_IDS",
    "Mode",
    "SourcingBrandOverviewOut",
    "SourcingBrandSkuOut",
    "SourcingBrandSupplierOut",
    "SourcingBulkRuleIn",
    "SourcingBulkRuleOut",
    "SourcingBulkRuleResultOut",
    "SourcingDecisionOut",
    "SourcingRuleIn",
    "SourcingRuleListOut",
    "SourcingRuleOut",
]
