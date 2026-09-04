"""Public surface of the ``gifts`` module.

``admin_router`` is the margin/config surface (Task 2). ``router`` is the
public catalog-browsing surface added in Task 3: live listing, hot offers,
app detail, and per-app DLC, all proxied from G-Engine through a
stale-while-error Redis cache — plus, since the pre-purchase check, the
``GET /gifts/steam-profile`` route (``gifts.profile``). ``is_gift_sku``,
``parse_invite_url``, and ``price_gift_line`` (Task 4) are the checkout hook
``orders/service.py`` calls to re-price a gift line server-side;
``STEAM_GIFT_SKU_CODE`` lives in ``checkout.py`` and is re-exported here
rather than the other way around, since this module already depends on
``checkout`` and the reverse would be a cycle. ``gifts.profile`` itself is
not re-exported here — like ``gifts.service``, it's internal, consumed
directly by ``gifts.routes`` only.
"""

from __future__ import annotations

from yupay.modules.gifts.admin import admin_router
from yupay.modules.gifts.checkout import (
    STEAM_GIFT_SKU_CODE,
    is_gift_sku,
    parse_invite_url,
    price_gift_line,
)
from yupay.modules.gifts.models import SteamGiftSettings
from yupay.modules.gifts.routes import router
from yupay.modules.gifts.schemas import (
    GiftAppDetailOut,
    GiftAppOut,
    GiftPackageOut,
    GiftProfileOut,
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

__all__ = [
    "STEAM_GIFT_SKU_CODE",
    "GiftAppDetailOut",
    "GiftAppOut",
    "GiftPackageOut",
    "GiftProfileOut",
    "GiftZonePriceOut",
    "GiftsAdminSettingsOut",
    "GiftsListOut",
    "GiftsSettingsIn",
    "SteamGiftSettings",
    "admin_router",
    "default_zone",
    "is_gift_sku",
    "load_margin_percent",
    "offered_zones",
    "parse_invite_url",
    "price_gift_line",
    "publish_margin",
    "router",
    "save_margin_percent",
]
