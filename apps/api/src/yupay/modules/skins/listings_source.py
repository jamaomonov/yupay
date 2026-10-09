"""Which supplier an item's live offers come from (ADR-0098).

``cs2_skins_source`` picks Waxpeer search (``listings``) or csmarket offers
(``listings_csmarket``). The item page route and the checkout both read through here, so
a price quoted on the page and the price checked at checkout come from the same place.
"""

from __future__ import annotations

from yupay.core.config import get_settings
from yupay.core.redis import get_redis
from yupay.modules.fulfillment.suppliers.csmarket_client import CsmarketClient
from yupay.modules.fulfillment.suppliers.waxpeer_client import WaxpeerClient
from yupay.modules.skins.listings import Listing, listings_for
from yupay.modules.skins.listings_csmarket import csmarket_listings_for
from yupay.modules.skins.models import SkinItem


def csmarket_client() -> CsmarketClient:
    """The csmarket client from settings (an empty key reads as not configured)."""
    settings = get_settings()
    return CsmarketClient(
        api_key=settings.csmarket_api_key,
        base_url=settings.csmarket_base_url,
        timeout_seconds=settings.csmarket_request_timeout_seconds,
    )


async def read_listings(item: SkinItem) -> tuple[list[Listing], bool]:
    """``(listings, degraded)`` from the configured source, cheapest first."""
    settings = get_settings()
    if settings.cs2_skins_source == "csmarket":
        return await csmarket_listings_for(
            item,
            client=csmarket_client(),
            redis=get_redis(),
            budget_per_minute=settings.csmarket_offers_per_minute
            if settings.csmarket_api_key
            else 0,
            timeout_seconds=settings.cs2_skins_listings_timeout_seconds,
        )
    client = WaxpeerClient(
        api_key=settings.waxpeer_api_key,
        base_url=settings.waxpeer_base_url,
        timeout_seconds=settings.cs2_skins_listings_timeout_seconds,
    )
    return await listings_for(
        item,
        client=client,
        redis=get_redis(),
        budget_per_minute=settings.cs2_skins_listings_bucket_per_minute
        if settings.waxpeer_api_key
        else 0,
    )


__all__ = ["csmarket_client", "read_listings"]
