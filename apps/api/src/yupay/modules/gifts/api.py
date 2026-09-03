"""Public surface of the ``gifts`` module.

Only the admin settings router exists yet. The public/miniapp browsing and
checkout routes (``router``) land in Task 3.
"""

from __future__ import annotations

from yupay.modules.gifts.admin import admin_router
from yupay.modules.gifts.models import SteamGiftSettings
from yupay.modules.gifts.schemas import GiftsAdminSettingsOut, GiftsSettingsIn
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
    "GiftsAdminSettingsOut",
    "GiftsSettingsIn",
    "SteamGiftSettings",
    "admin_router",
    "default_zone",
    "load_margin_percent",
    "offered_zones",
    "publish_margin",
    "save_margin_percent",
]
