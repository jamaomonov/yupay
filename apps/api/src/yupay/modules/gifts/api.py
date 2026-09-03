"""Public surface of the ``gifts`` module.

``admin_router`` is the margin/config surface (Task 2). ``router`` is the
public catalog-browsing surface added in Task 3: live listing, hot offers,
app detail, and per-app DLC, all proxied from G-Engine through a
stale-while-error Redis cache. Checkout routes land in a later task.
"""

from __future__ import annotations

from yupay.modules.gifts.admin import admin_router
from yupay.modules.gifts.models import SteamGiftSettings
from yupay.modules.gifts.routes import router
from yupay.modules.gifts.schemas import (
    GiftAppDetailOut,
    GiftAppOut,
    GiftPackageOut,
    GiftsAdminSettingsOut,
    GiftsListOut,
    GiftsSettingsIn,
    GiftZonePriceOut,
)
from yupay.modules.gifts.settings import (
    default_zone,
    load_margin_percent,
    offered_zones,
    publish_margin,
    save_margin_percent,
)

#: SKU code identifying the Steam gift product line, mirroring how other
#: single-SKU features (e.g. Telegram Stars) key off one well-known code
#: rather than a catalog flag.
STEAM_GIFT_SKU_CODE = "steam-gift"

__all__ = [
    "STEAM_GIFT_SKU_CODE",
    "GiftAppDetailOut",
    "GiftAppOut",
    "GiftPackageOut",
    "GiftZonePriceOut",
    "GiftsAdminSettingsOut",
    "GiftsListOut",
    "GiftsSettingsIn",
    "SteamGiftSettings",
    "admin_router",
    "default_zone",
    "load_margin_percent",
    "offered_zones",
    "publish_margin",
    "router",
    "save_margin_percent",
]
