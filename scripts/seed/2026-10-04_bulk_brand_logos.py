"""Give the bulk-imported brands a logo, from G2B's game images.

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-04_bulk_brand_logos.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-10-04_bulk_brand_logos.py

Only G2B publishes a picture per game (``GET /games`` → ``image_url``, a
492×492 PNG); FazerCards and G-Engine publish none, so a brand sold by them
alone keeps the accent-wash fallback until somebody uploads one in the admin.

The image is copied into our own media bucket under ``brand_logo/`` and the
brand points at ``cdn.yupay.uz`` — never hot-linked: a logo on a supplier's
host disappears the day they rename a game, and the storefront's image
optimiser only trusts our hosts. Stored as the PNG they serve (the container
has no image library to make a webp); 60–480 KB each, within the 5 MB media cap.

Scope: every brand with no ``logo_url`` and one active G2B game mapping — the
import's brands, plus any older brand (Oxide) still waiting on its logo.
Idempotent: a brand that already has a logo is left alone.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import yupay.main  # noqa: F401 -- registers every model
from sqlalchemy import text
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand
from yupay.modules.fulfillment.suppliers import REGISTRY
from yupay.modules.storage.client import get_s3_client
from yupay.modules.storage.service import _build_key, public_url_for

APPLY = os.environ.get("APPLY") == "1"
IMAGE_MIME = {"image/png", "image/jpeg", "image/webp"}


async def targets() -> list[dict[str, Any]]:
    async with get_session_factory()() as db:
        rows = await db.execute(text("""
            select b.id, b.slug, min(m.external_product_id) code
              from brands b join products p on p.brand_id = b.id
              join skus s on s.product_id = p.id
              join sku_supplier_mapping m on m.sku_id = s.id
             where b.logo_url is null and m.supplier_slug = 'g2b' and m.kind = 'game' and m.is_active
             group by b.id, b.slug having count(distinct m.external_product_id) = 1
             order by b.slug
        """))  # fmt: skip
        return [dict(r) for r in rows.mappings().all()]


async def fetch_image(client: httpx.AsyncClient, url: str) -> tuple[bytes, str] | None:
    """(bytes, content_type), or ``None`` when it is not an image we store."""
    resp = await client.get(url)
    if resp.status_code != 200:
        return None
    content_type = resp.headers.get("content-type", "").split(";")[0].strip()
    if content_type not in IMAGE_MIME or len(resp.content) > get_settings().media_max_upload_bytes:
        return None
    return resp.content, content_type


async def store(body: bytes, content_type: str) -> str:
    """Upload to the media bucket; returns the public URL."""
    key = _build_key("brand_logo", content_type)
    settings = get_settings()
    await asyncio.to_thread(
        get_s3_client().put_object,
        Bucket=settings.r2_bucket_media,
        Key=key,
        Body=body,
        ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable",
    )
    return public_url_for(key)


async def main() -> None:
    images = {
        str(g["code"]): g.get("image_url") for g in await REGISTRY["g2b"]._client().fetch_games()
    }
    todo = await targets()
    print(f"Брендов без логотипа с игрой G2B: {len(todo)}")
    done = missing = 0
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for b in todo:
            url = images.get(b["code"])
            if not url:
                missing += 1
                print(f"  - {b['slug']}: у G2B нет картинки")
                continue
            if not APPLY:
                continue
            try:
                got = await fetch_image(client, url)
            except httpx.HTTPError as exc:
                print(f"  ! {b['slug']}: {exc!s:.80}")
                continue
            if got is None:
                missing += 1
                print(f"  - {b['slug']}: не картинка или слишком большая")
                continue
            public = await store(*got)
            async with get_session_factory()() as db, db.begin():
                brand = await db.get(Brand, b["id"])
                if brand is not None and brand.logo_url is None:
                    brand.logo_url = public
                    done += 1
            await asyncio.sleep(0.2)
    print(
        f"Загружено: {done}, без источника: {missing}"
        if APPLY
        else "APPLY не задан — ничего не записано."
    )


if __name__ == "__main__":
    asyncio.run(main())
