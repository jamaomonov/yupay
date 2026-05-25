"""``/api/v1`` — public API mount.

Modules register their routers here. Keep the imports alphabetical for diff readability.
"""

from __future__ import annotations

from fastapi import APIRouter

from yupay.modules.admin.api import admin_router as admin_admin_router
from yupay.modules.audit.api import admin_router as audit_admin_router
from yupay.modules.auth.api import router as auth_router
from yupay.modules.catalog.admin_routes import router as catalog_admin_router
from yupay.modules.catalog.api import router as catalog_router
from yupay.modules.fulfillment.api import admin_router as fulfillment_admin_router
from yupay.modules.fulfillment.api import router as fulfillment_router
from yupay.modules.fx.api import admin_router as fx_admin_router
from yupay.modules.fx.api import router as fx_router
from yupay.modules.inventory.api import admin_router as inventory_admin_router
from yupay.modules.orders.api import admin_router as orders_admin_router
from yupay.modules.orders.api import router as orders_router
from yupay.modules.payments.api import admin_router as payments_admin_router
from yupay.modules.payments.api import admin_webhook_router as payments_admin_webhook_router
from yupay.modules.payments.api import router as payments_router
from yupay.modules.payments.api import webhook_router as payments_webhook_router
from yupay.modules.sourcing.api import admin_router as sourcing_admin_router
from yupay.modules.stats.api import admin_router as stats_admin_router
from yupay.modules.storage.api import admin_router as storage_admin_router
from yupay.modules.users.api import admin_router as users_admin_router
from yupay.modules.users.api import router as users_router
from yupay.modules.wallet.api import admin_router as wallet_admin_router
from yupay.modules.wallet.api import router as wallet_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(admin_admin_router)
router.include_router(audit_admin_router)
router.include_router(catalog_router)
router.include_router(catalog_admin_router)
router.include_router(fulfillment_router)
router.include_router(fulfillment_admin_router)
router.include_router(fx_router)
router.include_router(fx_admin_router)
router.include_router(orders_router)
router.include_router(orders_admin_router)
router.include_router(payments_router)
router.include_router(payments_admin_router)
router.include_router(payments_admin_webhook_router)
router.include_router(payments_webhook_router)
router.include_router(inventory_admin_router)
router.include_router(sourcing_admin_router)
router.include_router(stats_admin_router)
router.include_router(storage_admin_router)
router.include_router(users_router)
router.include_router(users_admin_router)
router.include_router(wallet_router)
router.include_router(wallet_admin_router)
