"""Add the free-amount Telegram Stars SKU beside the packages.

Run inside the api container (needs ``GENGINE_API_KEY`` for the live rate):

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-18_telegram_stars_any_amount.py

The packages stay: most buyers want "500 stars" and a grid answers that in one
tap. This is the line for everyone else — the same shape as the Steam wallet,
except the customer types **stars** rather than dollars, because stars is what
they are buying and $0.0155 each is arithmetic the page can do for them.

Three fields carry that:

* ``variable_amount`` — the customer names the amount, as Steam does.
* ``amount_unit`` / ``units_per_usd`` — what they type and what it converts at
  (migration 0047). The USD bounds stay authoritative and stay in USD.
* ``rate_multiplier`` — the margin, applied to the guarded FX rate exactly as
  Steam's is. It is set to match the 20% the packages already carry.

Bounds are 50 stars (Telegram's own floor, so nothing smaller can be sold) to
50 000, expressed in USD because that is what the column means.

Idempotent: re-running finds the SKU and leaves it alone.
"""

from __future__ import annotations

import asyncio
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.catalog import admin_schemas as cat_schemas
from yupay.modules.catalog import admin_service as catalog
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.fulfillment.suppliers.gengine_client import GEngineClient
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

ADMIN_ID = "00000000-0000-7000-8000-000000000001"
STARS_SERVICE_ID = 72
PRODUCT_SLUG = "telegram-stars"
SKU_CODE = "tg-stars-any"

MIN_STARS = 50
MAX_STARS = 50_000
#: The margin the packages carry, as a multiplier on the guarded FX rate.
RATE_MULTIPLIER = Decimal("1.2000")


async def main() -> None:
    settings = get_settings()
    if not settings.gengine_api_key:
        raise SystemExit("GENGINE_API_KEY is not set — the import needs it to read the live rate")
    client = GEngineClient(
        api_key=settings.gengine_api_key,
        base_url=settings.gengine_base_url,
        timeout_seconds=settings.gengine_request_timeout_seconds,
    )

    rate: Decimal | None = None
    for offset in (0, 100, 200):
        page = await client.list_recharge_services(limit=100, offset=offset)
        if not page:
            break
        for service in page:
            if service.get("id") == STARS_SERVICE_ID:
                rate = Decimal(str((service.get("unfixed_details") or {}).get("rate") or 0))
    if not rate or rate <= 0:
        raise SystemExit(
            f"G-Engine service {STARS_SERVICE_ID} reports no usable rate — cannot price Stars"
        )
    print(f"stars: rate={rate} per USD (${Decimal(1) / rate:.6f} each)")

    def usd(stars: int) -> Decimal:
        return (Decimal(stars) / rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

    async with get_session_factory()() as session:
        product: Any = (
            await session.execute(select(Product).where(Product.slug == PRODUCT_SLUG))
        ).scalar_one_or_none()
        if product is None:
            raise SystemExit(
                f"product {PRODUCT_SLUG} does not exist — run the Telegram import first"
            )

        existing = (
            await session.execute(select(Sku).where(Sku.sku_code == SKU_CODE))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"{SKU_CODE}: exists — skipped")
            return

        sku = await catalog.create_sku(
            session,
            cat_schemas.SkuCreate(
                product_id=str(product.id),
                sku_code=SKU_CODE,
                denomination="Любое количество",
                # A placeholder, as on every variable SKU: the amount the
                # customer types is what gets billed.
                price_usd=Decimal("1"),
                variable_amount=True,
                min_amount_usd=usd(MIN_STARS),
                max_amount_usd=usd(MAX_STARS),
                rate_multiplier=RATE_MULTIPLIER,
                amount_unit="Stars",
                units_per_usd=rate,
                # Last in the grid: the packages answer most intents first.
                sort_order=99,
            ),
        )
        await upsert_mapping(
            session,
            MappingUpsert(
                sku_id=sku.id,
                supplier_slug="gengine",
                kind="game",
                external_product_id=str(STARS_SERVICE_ID),
                external_variant_id=None,
                # Unused for a variable line — the adapter re-derives the star
                # count from what was actually charged — but the column is not
                # nullable, and 1 is the neutral value.
                quantity=1,
                extra={},
                is_active=True,
                updated_by=ADMIN_ID,
            ),
        )
        await session.commit()
        print(
            f"{SKU_CODE}: created — {MIN_STARS}..{MAX_STARS} stars "
            f"(${usd(MIN_STARS)}..${usd(MAX_STARS)}), ×{RATE_MULTIPLIER}"
        )


asyncio.run(main())
