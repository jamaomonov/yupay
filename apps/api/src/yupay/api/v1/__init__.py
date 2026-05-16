"""``/api/v1`` — public API mount.

Modules register their routers here. Keep the imports alphabetical for diff readability.
"""

from __future__ import annotations

from fastapi import APIRouter

from yupay.modules.auth.api import router as auth_router
from yupay.modules.catalog.admin_routes import router as catalog_admin_router
from yupay.modules.catalog.api import router as catalog_router
from yupay.modules.fulfillment.api import admin_router as fulfillment_admin_router
from yupay.modules.fulfillment.api import router as fulfillment_router
from yupay.modules.fx.api import router as fx_router
from yupay.modules.orders.api import admin_router as orders_admin_router
from yupay.modules.orders.api import router as orders_router
from yupay.modules.payments.api import admin_router as payments_admin_router
from yupay.modules.payments.api import router as payments_router
from yupay.modules.payments.api import webhook_router as payments_webhook_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(catalog_router)
router.include_router(catalog_admin_router)
router.include_router(fulfillment_router)
router.include_router(fulfillment_admin_router)
router.include_router(fx_router)
router.include_router(orders_router)
router.include_router(orders_admin_router)
router.include_router(payments_router)
router.include_router(payments_admin_router)
router.include_router(payments_webhook_router)
