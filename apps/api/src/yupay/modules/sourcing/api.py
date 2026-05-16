"""Public surface of the ``sourcing`` module."""

from yupay.modules.sourcing.models import SkuSourcingRule
from yupay.modules.sourcing.routes import admin_router
from yupay.modules.sourcing.schemas import (
    Mode,
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
    "Decision",
    "Mode",
    "SkuSourcingRule",
    "SourcingDecisionOut",
    "SourcingRuleIn",
    "SourcingRuleListOut",
    "SourcingRuleOut",
    "admin_router",
    "delete_rule",
    "get_rule",
    "list_rules",
    "resolve_for_sku",
    "set_rule",
]
