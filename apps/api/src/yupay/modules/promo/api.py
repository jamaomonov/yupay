"""Public surface of the ``promo`` module — the only thing other modules import."""

from yupay.modules.promo.models import PromoCode, PromoRedemption
from yupay.modules.promo.routes import admin_router, router
from yupay.modules.promo.schemas import (
    PromoAdminListOut,
    PromoAdminOut,
    PromoCreateIn,
    PromoRedeemIn,
    PromoRedeemOut,
)
from yupay.modules.promo.service import create_code, deactivate, list_codes, redeem

__all__ = [
    "PromoAdminListOut",
    "PromoAdminOut",
    "PromoCode",
    "PromoCreateIn",
    "PromoRedeemIn",
    "PromoRedeemOut",
    "PromoRedemption",
    "admin_router",
    "create_code",
    "deactivate",
    "list_codes",
    "redeem",
    "router",
]
