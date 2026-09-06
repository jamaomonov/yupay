"""``/api/v1`` — public API mount.

Modules register their routers here. Keep the imports alphabetical for diff readability.
"""

from __future__ import annotations

from fastapi import APIRouter

from yupay.api.webhooks.g2b import router as g2b_webhook_router
from yupay.modules.admin.api import admin_router as admin_admin_router

# Imported from ``routes`` rather than the module facade on purpose: the
# affiliate facade is imported by orders.service and payments.service, and
# a router re-exported from it would close a cycle back through here.
from yupay.modules.affiliate.routes import admin_router as affiliate_admin_router
from yupay.modules.affiliate.routes import router as affiliate_router
from yupay.modules.audit.api import admin_router as audit_admin_router
from yupay.modules.auth.api import router as auth_router
from yupay.modules.broadcasts.api import admin_router as broadcasts_admin_router
from yupay.modules.catalog.admin_routes import router as catalog_admin_router
from yupay.modules.catalog.api import router as catalog_router
from yupay.modules.click.api import router as click_router
from yupay.modules.evidence.api import admin_router as evidence_admin_router
from yupay.modules.fulfillment.api import admin_router as fulfillment_admin_router
from yupay.modules.fulfillment.api import router as fulfillment_router
from yupay.modules.fx.api import admin_router as fx_admin_router
from yupay.modules.fx.api import router as fx_router
from yupay.modules.gifts.api import admin_router as gifts_admin_router
from yupay.modules.gifts.api import router as gifts_router
from yupay.modules.integrations.api import admin_router as integrations_admin_router
from yupay.modules.integrations.api import router as integrations_router
from yupay.modules.inventory.api import admin_router as inventory_admin_router

# Imported from ``admin_routes`` rather than the module facade on purpose —
# the merchants facade is imported by service-layer callers (orders, and the
# M2+ machine API), and a router re-exported from it would close a cycle back
# through here. Same rule as ``affiliate.routes`` above.
from yupay.modules.merchants.admin_routes import admin_router as merchants_admin_router
from yupay.modules.merchants.admin_routes import (
    catalog_b2b_router as merchants_catalog_b2b_router,
)
from yupay.modules.orders.api import admin_router as orders_admin_router
from yupay.modules.orders.api import router as orders_router
from yupay.modules.payme.api import router as payme_router
from yupay.modules.payments.api import admin_router as payments_admin_router
from yupay.modules.payments.api import admin_webhook_router as payments_admin_webhook_router
from yupay.modules.payments.api import router as payments_router
from yupay.modules.payments.api import webhook_router as payments_webhook_router
from yupay.modules.promo.api import admin_router as promo_admin_router
from yupay.modules.promo.api import router as promo_router
from yupay.modules.realtime.api import router as realtime_router
from yupay.modules.reviews.api import admin_router as reviews_admin_router
from yupay.modules.reviews.api import router as reviews_router
from yupay.modules.sourcing.api import admin_router as sourcing_admin_router
from yupay.modules.stats.api import admin_router as stats_admin_router
from yupay.modules.storage.api import admin_router as storage_admin_router
from yupay.modules.users.api import admin_router as users_admin_router
from yupay.modules.users.api import router as users_router
from yupay.modules.uzum.api import router as uzum_router
from yupay.modules.wallet.api import admin_router as wallet_admin_router
from yupay.modules.wallet.api import router as wallet_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(admin_admin_router)
router.include_router(audit_admin_router)
router.include_router(broadcasts_admin_router)
router.include_router(catalog_router)
router.include_router(catalog_admin_router)
router.include_router(evidence_admin_router)
router.include_router(fulfillment_router)
router.include_router(fulfillment_admin_router)
router.include_router(fx_router)
router.include_router(fx_admin_router)
router.include_router(gifts_router)
router.include_router(gifts_admin_router)
router.include_router(orders_router)
router.include_router(orders_admin_router)
router.include_router(payments_router)
router.include_router(payments_admin_router)
router.include_router(payments_admin_webhook_router)
router.include_router(payments_webhook_router)
router.include_router(payme_router)
router.include_router(uzum_router)
router.include_router(click_router)
router.include_router(g2b_webhook_router)
router.include_router(integrations_admin_router)
router.include_router(integrations_router)
router.include_router(inventory_admin_router)
router.include_router(merchants_admin_router)
router.include_router(merchants_catalog_b2b_router)
router.include_router(sourcing_admin_router)
router.include_router(stats_admin_router)
router.include_router(storage_admin_router)
router.include_router(users_router)
router.include_router(users_admin_router)
router.include_router(wallet_router)
router.include_router(affiliate_router)
router.include_router(affiliate_admin_router)
router.include_router(promo_router)
router.include_router(promo_admin_router)
router.include_router(reviews_router)
router.include_router(reviews_admin_router)
router.include_router(realtime_router)
router.include_router(wallet_admin_router)
