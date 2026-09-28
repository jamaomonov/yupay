"""Public interface of the ``skins`` module (AGENTS.md §4)."""

from yupay.modules.skins.admin import admin_router
from yupay.modules.skins.bymykel import import_catalog
from yupay.modules.skins.models import SkinItem, SkinPricingRules, SkinSearchAlias
from yupay.modules.skins.prices import sync_prices
from yupay.modules.skins.pricing import DEFAULT_RULES, PricingRules, Quote, quote
from yupay.modules.skins.routes import router
from yupay.modules.skins.settings import load_rules

__all__ = [
    "DEFAULT_RULES",
    "PricingRules",
    "Quote",
    "SkinItem",
    "SkinPricingRules",
    "SkinSearchAlias",
    "admin_router",
    "import_catalog",
    "load_rules",
    "quote",
    "router",
    "sync_prices",
]
