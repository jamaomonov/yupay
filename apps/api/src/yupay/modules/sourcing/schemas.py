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
    supplier that actually has a mapping row among the brand's SKUs
    (``integrations.models``, ADR-0019). The fixed half means a supplier
    the SKU has never been mapped to still gets a row here, with
    ``has_active_mapping=False`` and no cost, so an operator comparing
    suppliers can see it as a switch target rather than it silently being
    absent. The union half means a supplier outside that fixed set (e.g.
    waxpeer) that actually won the live route via a mapping still appears
    here — otherwise the reported ``primary`` could name a supplier absent
    from its own comparison list, which is the invariant this list exists
    to uphold. Sorted alphabetically for a stable order.

    ``latest_cost_usdt`` is a string (mirrors
    ``integrations.schemas.PricePointOut.cost_usdt``, the other DTO that
    surfaces a ``supplier_price_history`` row) rather than the ``Decimal``
    used for the SKU's own ``price_usd``/``cost_usdt`` below — those two
    are ``Sku`` columns exposed the way ``catalog.admin_schemas.AdminSkuOut``
    already exposes them.
    """

    supplier_slug: str
    has_active_mapping: bool
    latest_cost_usdt: str | None
    captured_at: datetime | None


class SourcingBrandSkuOut(BaseModel):
    """One active SKU's sourcing picture for the brand-overview screen."""

    sku_id: str
    sku_code: str
    denomination: str | None
    product_slug: str
    price_usd: Decimal
    cost_usdt: Decimal | None
    primary: str
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
