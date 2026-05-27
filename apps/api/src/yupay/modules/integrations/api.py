"""Public surface of the ``integrations`` module.

Other modules MUST import from here, never from ``service`` / ``models`` /
``routes`` directly. This keeps the module's internal layout free to evolve
without touching callers (e.g. swapping single-account env vars for a
``supplier_credentials`` table in a future sprint).
"""

from yupay.modules.integrations.models import SkuSupplierMapping, SupplierCatalogCache
from yupay.modules.integrations.routes import admin_router
from yupay.modules.integrations.schemas import (
    CatalogEntryOut,
    CatalogKind,
    CatalogListOut,
    CatalogSyncOut,
    CheckPlayerIn,
    CheckPlayerOut,
    CostSyncResult,
    GameDenomListOut,
    GameDenomOut,
    GameFieldsOut,
    MappingKind,
    PriceHistoryOut,
    PricePointOut,
    PriceRefreshOut,
    SupplierHealthOut,
    SupplierMappingIn,
    SupplierMappingListOut,
    SupplierMappingOut,
    SupplierMappingUpsertOut,
)
from yupay.modules.integrations.service import (
    MappingUpsert,
    delete_mapping,
    get_mapping,
    list_catalog,
    list_mappings,
    upsert_catalog_entry,
    upsert_mapping,
)

__all__ = [
    "CatalogEntryOut",
    "CatalogKind",
    "CatalogListOut",
    "CatalogSyncOut",
    "CheckPlayerIn",
    "CheckPlayerOut",
    "CostSyncResult",
    "GameDenomListOut",
    "GameDenomOut",
    "GameFieldsOut",
    "MappingKind",
    "MappingUpsert",
    "PriceHistoryOut",
    "PricePointOut",
    "PriceRefreshOut",
    "SkuSupplierMapping",
    "SupplierCatalogCache",
    "SupplierHealthOut",
    "SupplierMappingIn",
    "SupplierMappingListOut",
    "SupplierMappingOut",
    "SupplierMappingUpsertOut",
    "admin_router",
    "delete_mapping",
    "get_mapping",
    "list_catalog",
    "list_mappings",
    "upsert_catalog_entry",
    "upsert_mapping",
]
