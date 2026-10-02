"""Super Value Pass for Mobile Legends (global).

In the game it is «Супервыгодный пропуск» / Super Value Pass: $1.00 for 150
diamonds over seven days of logging in (owner's screenshot, 2026-10-02). Of our
suppliers only G2B sells it, under the name **"Diamond Pass"** (id 7949, $0.755
on 2026-10-02) in the same `mlbb` region the brand's other packs map to. NOVA,
FazerCards and G-Engine do not carry it, so auto routing picks G2B and no
sourcing rule is needed. Mind the name clash: our `mlbb-weekly` SKU is called
"Weekly Diamond Pass" and maps to G2B's "Weekly", not to this.

Margin and wholesale markup copy the neighbouring Weekly Elite Pack, which costs
the same at G2B (12 % retail, 5 % B2B). ``price_usd`` comes from
``_price_from_margin``, the function the hourly refresh re-derives with. The
SKU joins «Пропуски и наборы» (`mlbb-passes`) at the top, the cheapest slot,
and takes Weekly Elite Pack's image until a proper one is uploaded.

Dry run by default:

    docker compose -f docker-compose.prod.yml exec -T api \\
        python - < scripts/seed/2026-10-02_mlbb_super_value_pass.py

Then commit it:

    docker compose -f docker-compose.prod.yml exec -T -e APPLY=1 api \\
        python - < scripts/seed/2026-10-02_mlbb_super_value_pass.py
"""

from __future__ import annotations

import asyncio
import os
from decimal import Decimal

from sqlalchemy import select, update
from yupay.core.db import get_session_factory
from yupay.core.ids import new_id
from yupay.modules.catalog.admin_service import _price_from_margin
from yupay.modules.catalog.models import Product, Sku
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

APPLY = os.environ.get("APPLY") == "1"

SKU_CODE = "mlbb-super-value-pass"
DENOMINATION = "Super Value Pass"
PRODUCT_SLUG = "mlbb-passes"
COST_USDT = Decimal("0.755")
MARGIN_PCT = Decimal("12")
B2B_MARKUP_PCT = Decimal("5")
G2B = ("mlbb", "Diamond Pass")
IMAGE_FROM = "mlbb-weekly-elite-pack"


async def main() -> None:
    price = _price_from_margin(COST_USDT, MARGIN_PCT)
    async with get_session_factory()() as db:
        if (await db.execute(select(Sku.id).where(Sku.sku_code == SKU_CODE))).first():
            print(f"skip: {SKU_CODE} already exists")
            return
        product_id = (
            await db.execute(select(Product.id).where(Product.slug == PRODUCT_SLUG))
        ).scalar_one()
        image_url = (
            await db.execute(select(Sku.image_url).where(Sku.sku_code == IMAGE_FROM))
        ).scalar_one_or_none()
        print(
            f"create {SKU_CODE} «{DENOMINATION}» in {PRODUCT_SLUG}: cost ${COST_USDT} -> ${price}"
        )
        if not APPLY:
            print("dry run — nothing written. Re-run with APPLY=1.")
            return

        # Make room at the top: the pass is the cheapest thing in the product.
        await db.execute(
            update(Sku).where(Sku.product_id == product_id).values(sort_order=Sku.sort_order + 1)
        )
        sku = Sku(
            id=new_id(),
            product_id=product_id,
            sku_code=SKU_CODE,
            denomination=DENOMINATION,
            region="global",
            price_usd=price,
            cost_usdt=COST_USDT,
            margin_percent=MARGIN_PCT,
            b2b_markup_pct=B2B_MARKUP_PCT,
            image_url=image_url,
            sort_order=0,
            active=True,
            visible_b2b=True,
        )
        db.add(sku)
        await db.flush()
        await upsert_mapping(
            db,
            MappingUpsert(
                sku_id=sku.id,
                supplier_slug="g2b",
                kind="game",
                external_product_id=G2B[0],
                external_variant_id=G2B[1],
                quantity=1,
                extra={},
                is_active=True,
                updated_by="mlbb-super-value-pass-2026-10-02",
            ),
        )
        await db.commit()
        print(f"created {SKU_CODE} ({sku.id})")


if __name__ == "__main__":
    asyncio.run(main())
