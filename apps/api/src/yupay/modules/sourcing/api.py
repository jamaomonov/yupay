"""Public surface of the ``sourcing`` module."""

from yupay.modules.sourcing.brand_overview import get_brand_overview
from yupay.modules.sourcing.bulk_rules import bulk_set_rules
from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.sourcing.routes import admin_router
from yupay.modules.sourcing.schemas import (
    MAX_BULK_SKU_IDS,
    Mode,
    SourcingBrandOverviewOut,
    SourcingBrandSkuOut,
    SourcingBrandSupplierOut,
    SourcingBulkRuleIn,
    SourcingBulkRuleOut,
    SourcingBulkRuleResultOut,
    SourcingDecisionOut,
    SourcingRuleIn,
    SourcingRuleListOut,
    SourcingRuleOut,
)
from yupay.modules.sourcing.service import (
    DEFAULT_FALLBACK_SUPPLIER,
    Decision,
    delete_rule,
    get_rule,
    list_rules,
    resolve_for_sku,
    set_rule,
)

__all__ = [
    "DEFAULT_FALLBACK_SUPPLIER",
    "MAX_BULK_SKU_IDS",
    "Decision",
    "Mode",
    "SkuSourcingRule",
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
    "admin_router",
    "bulk_set_rules",
    "delete_rule",
    "get_brand_overview",
    "get_rule",
    "list_rules",
    "resolve_for_sku",
    "set_rule",
]
