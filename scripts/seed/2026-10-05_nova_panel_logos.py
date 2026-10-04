"""Logos for the brands no supplier API pictures: NovaGifts' panel covers.

    docker exec -i yupay-prod-api-1 python - < scripts/seed/2026-10-05_nova_panel_logos.py
    docker exec -i -e APPLY=1 yupay-prod-api-1 python - < scripts/seed/2026-10-05_nova_panel_logos.py

After ``2026-10-04_bulk_brand_logos.py`` (G2B images) and the sibling copies,
67 brands still had no logo — games only FazerCards sells. NovaGifts resells
the same categories and its reseller panel (``/catalog/topups``, read
2026-10-05 while signed in) shows a cover per game, served publicly from
``nova-gifts.com/api/v2/media/game-key-covers/…``. Matched by name, by hand
where the panel groups regions («Call of Duty Mobile - Activision» covers all
five of our regional brands). Ten brands have no cover there either (the
live-chat apps: Dazz, Hago, Jaco, Livu, MICO, Migo, Sawa, TopTop, City of
Crime) and stay without one.

Same storage rule as the G2B pass: copied into our media bucket, never
hot-linked. Idempotent: a brand that already has a logo is left alone.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import yupay.main  # noqa: F401 -- registers every model
from sqlalchemy import select
from yupay.core.config import get_settings
from yupay.core.db import get_session_factory
from yupay.modules.catalog.models import Brand
from yupay.modules.storage.client import get_s3_client
from yupay.modules.storage.service import _build_key, public_url_for

APPLY = os.environ.get("APPLY") == "1"
IMAGE_MIME = {"image/png", "image/jpeg", "image/webp"}

COVERS: dict[str, str] = {
    "badlanders": "https://nova-gifts.com/api/v2/media/game-key-covers/c7bcad91-5222-47da-90bf-ed81ca9ecddd.jpg",
    "ballistic-hero-vng": "https://nova-gifts.com/api/v2/media/game-key-covers/b6f49c82-0932-49d3-95db-de7717b08cb0.png",
    "be-the-king": "https://nova-gifts.com/api/v2/media/game-key-covers/1b26ca92-db76-4c08-a876-5afd1d6ebe76.png",
    "blade-x-odyssey-of-heroes": "https://nova-gifts.com/api/v2/media/game-key-covers/3cca4935-7f9d-4276-97f3-2c25ba7a9c58.jpg",
    "call-of-duty-mobile-activision-ca": "https://nova-gifts.com/api/v2/media/game-key-covers/7ced4f08-4353-4d52-bbab-c62633898c10.webp",
    "call-of-duty-mobile-activision-in": "https://nova-gifts.com/api/v2/media/game-key-covers/7ced4f08-4353-4d52-bbab-c62633898c10.webp",
    "call-of-duty-mobile-activision-kz": "https://nova-gifts.com/api/v2/media/game-key-covers/7ced4f08-4353-4d52-bbab-c62633898c10.webp",
    "call-of-duty-mobile-activision-sa": "https://nova-gifts.com/api/v2/media/game-key-covers/7ced4f08-4353-4d52-bbab-c62633898c10.webp",
    "call-of-duty-mobile-activision-us": "https://nova-gifts.com/api/v2/media/game-key-covers/7ced4f08-4353-4d52-bbab-c62633898c10.webp",
    "capcut": "https://nova-gifts.com/api/v2/media/game-key-covers/0943f75d-90d8-4356-bbe7-a473b301a09d.png",
    "captain-tsubasa-ace": "https://nova-gifts.com/api/v2/media/game-key-covers/3d437fb4-e9c9-49c9-bc4e-5e140116924c.jpg",
    "chamet": "https://nova-gifts.com/api/v2/media/game-key-covers/8f09a795-1b5a-4e76-b708-4005b32a55dc.png",
    "clash-of-plants": "https://nova-gifts.com/api/v2/media/game-key-covers/dc8e5cb7-7c39-410a-a309-41b6d7b5423f.webp",
    "conquer-online": "https://nova-gifts.com/api/v2/media/game-key-covers/eb1baa2c-d63d-49c6-9180-da422955f21e.png",
    "crystalfall": "https://nova-gifts.com/api/v2/media/game-key-covers/49f599e5-6a42-4a91-94c9-bb2d6565935d.jpg",
    "dream-and-lethe-record": "https://nova-gifts.com/api/v2/media/game-key-covers/5daf26db-9454-41f0-b77b-8d49fe94b6ef.webp",
    "dynasty-heroes-legend-samkok": "https://nova-gifts.com/api/v2/media/game-key-covers/65015577-bd8e-4a5d-ac00-16c87c12d5b6.webp",
    "ensemble-stars-music": "https://nova-gifts.com/api/v2/media/game-key-covers/07629932-d41a-44b9-abd2-7225aa2d062b.jpg",
    "extraordinary-ones": "https://nova-gifts.com/api/v2/media/game-key-covers/5a236d32-65da-4234-96ae-02a190faa313.jpg",
    "fashion-dream": "https://nova-gifts.com/api/v2/media/game-key-covers/356bd541-a445-4148-8fe4-70816355b78f.png",
    "firefly-live": "https://nova-gifts.com/api/v2/media/game-key-covers/44c98e6e-9a68-4473-9f24-2f2548861a4c.jpg",
    "football-master-2": "https://nova-gifts.com/api/v2/media/game-key-covers/44fb5be1-b667-4a5a-9fd5-e9e88dead084.jpg",
    "garena-speed-drifters": "https://nova-gifts.com/api/v2/media/game-key-covers/552a890f-6b13-4770-b734-3e1bce72e255.png",
    "heesay": "https://nova-gifts.com/api/v2/media/game-key-covers/7e795078-c37e-4866-9828-8b5afb88c60a.jpg",
    "heroes-evolved": "https://nova-gifts.com/api/v2/media/game-key-covers/655a7fe4-ce10-49ee-9300-db0412afc285.png",
    "hyper-front": "https://nova-gifts.com/api/v2/media/game-key-covers/080a24ed-8c89-4463-b138-83065249f493.jpg",
    "idol-party": "https://nova-gifts.com/api/v2/media/game-key-covers/1f06189e-05ed-47f6-936b-648703ccdafe.jpg",
    "infinite-lagrange": "https://nova-gifts.com/api/v2/media/game-key-covers/f0dd115d-de8c-424d-8b74-28c55a427908.webp",
    "isekai-feast-tales-of-recipes": "https://nova-gifts.com/api/v2/media/game-key-covers/f88e7baf-3895-4b15-8a97-e45f2e13c022.jpg",
    "journey-renewed-fate-fantasy": "https://nova-gifts.com/api/v2/media/game-key-covers/89674c7d-0f52-4f5f-b059-731cee9d1206.jpg",
    "legacy-of-discord-furiouswings": "https://nova-gifts.com/api/v2/media/game-key-covers/aad5562d-56eb-4a86-bb4e-3bba6bdcc761.png",
    "lita": "https://nova-gifts.com/api/v2/media/game-key-covers/838a76e0-512f-4f7e-aeba-57eb8d304c92.webp",
    "lords-mobile": "https://nova-gifts.com/api/v2/media/game-key-covers/d217c4f7-94c0-4a82-bb87-41f84fa8e242.png",
    "mangatoon-read-comics-novel": "https://nova-gifts.com/api/v2/media/game-key-covers/25164347-345b-4f73-ba37-8cbceeda6a51.webp",
    "mirage-perfect-skyline": "https://nova-gifts.com/api/v2/media/game-key-covers/7960d420-7519-47a0-aa92-6ff707172e0b.png",
    "mu-origin-3-asia": "https://nova-gifts.com/api/v2/media/game-key-covers/f3566580-87ce-4463-8072-efc1d88c8e07.png",
    "nimo-tv": "https://nova-gifts.com/api/v2/media/game-key-covers/a3e784c9-df8b-41d8-b15e-c1cbfddbb4b5.webp",
    "octopath-traveler-cotc": "https://nova-gifts.com/api/v2/media/game-key-covers/2663dd10-baba-487d-afa1-ea494fb94250.webp",
    "omega-legends": "https://nova-gifts.com/api/v2/media/game-key-covers/2f733b59-6811-4a22-8a9b-5b8f09a0815d.jpg",
    "point-blank-id": "https://nova-gifts.com/api/v2/media/game-key-covers/383518c7-554e-448b-8063-350ac697ca12.png",
    "pokemon-unite-ph": "https://nova-gifts.com/api/v2/media/game-key-covers/6c79e7bf-b0aa-4db7-86c6-0f2f6eaa4f92.jpg",
    "pubg-new-state": "https://nova-gifts.com/api/v2/media/game-key-covers/fa020ab7-4736-44aa-a639-b31be8a2e2d7.webp",
    "qq-coin-q": "https://nova-gifts.com/api/v2/media/game-key-covers/9cb26acf-6cdc-4b92-b0fa-5abd84acec4e.webp",
    "ragnarok-m-classic-sea": "https://nova-gifts.com/api/v2/media/game-key-covers/ffece318-b3d3-49fb-a80e-49d355985d07.webp",
    "ragnarok-m-eternal-love-sea": "https://nova-gifts.com/api/v2/media/game-key-covers/ddae376a-2af7-480b-9f49-d13e938a0439.webp",
    "ragnarok-tactics": "https://nova-gifts.com/api/v2/media/game-key-covers/15e9eb6b-a2de-4111-a146-1e14b730105e.jpg",
    "realms-of-pixel": "https://nova-gifts.com/api/v2/media/game-key-covers/3cad1fdf-5eac-40c7-b185-33ff5913fc2e.webp",
    "slam-dunk": "https://nova-gifts.com/api/v2/media/game-key-covers/79db17f1-e6e8-49cd-832a-ad17198453ef.jpg",
    "sugo-online-chat-party": "https://nova-gifts.com/api/v2/media/game-key-covers/55d56217-4dad-4e75-b6a7-bb82fcc563df.jpg",
    "sword-of-fire-and-ice": "https://nova-gifts.com/api/v2/media/game-key-covers/b57c223e-a206-45da-aba4-fe414abd5090.jpg",
    "tik-tok-china": "https://nova-gifts.com/api/v2/media/game-key-covers/9aac875e-15b0-4e49-bb00-8a73c7ae93f7.png",
    "tom-and-jerry-chase": "https://nova-gifts.com/api/v2/media/game-key-covers/2b232ebf-5c78-4548-a80d-b214884bef12.webp",
    "ulala-idle-adventure": "https://nova-gifts.com/api/v2/media/game-key-covers/e1ed3ac5-290e-4e33-9f56-4bf44a69065c.jpg",
    "warborne-above-ashes": "https://nova-gifts.com/api/v2/media/game-key-covers/ccff4bc7-871d-4576-b885-1de5f225295c.jpg",
    "wesing": "https://nova-gifts.com/api/v2/media/game-key-covers/ece60fce-2fd6-401e-9243-d512973e792a.webp",
    "yoho-group-voice-chat-room": "https://nova-gifts.com/api/v2/media/game-key-covers/6a9d1a47-7bb5-4574-826a-fa71692b6b29.jpg",
}


async def store(body: bytes, content_type: str) -> str:
    key = _build_key("brand_logo", content_type)
    await asyncio.to_thread(
        get_s3_client().put_object,
        Bucket=get_settings().r2_bucket_media,
        Key=key,
        Body=body,
        ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable",
    )
    return public_url_for(key)


async def main() -> None:
    done = skipped = 0
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for slug, url in COVERS.items():
            async with get_session_factory()() as db:
                brand = (
                    await db.execute(select(Brand).where(Brand.slug == slug))
                ).scalar_one_or_none()
                if brand is None or brand.logo_url is not None:
                    skipped += 1
                    continue
            print(f"  {slug}")
            if not APPLY:
                continue
            resp = await client.get(url)
            content_type = resp.headers.get("content-type", "").split(";")[0].strip()
            if resp.status_code != 200 or content_type not in IMAGE_MIME:
                print(f"  ! {slug}: HTTP {resp.status_code} {content_type}")
                continue
            if len(resp.content) > get_settings().media_max_upload_bytes:
                print(f"  ! {slug}: {len(resp.content)} bytes is over the media cap")
                continue
            public = await store(resp.content, content_type)
            async with get_session_factory()() as db, db.begin():
                brand = (await db.execute(select(Brand).where(Brand.slug == slug))).scalar_one()
                if brand.logo_url is None:
                    brand.logo_url = public
                    done += 1
            await asyncio.sleep(0.2)
    print(
        f"Загружено: {done}, пропущено (есть логотип / нет бренда): {skipped}"
        if APPLY
        else "APPLY не задан — ничего не записано."
    )


if __name__ == "__main__":
    asyncio.run(main())
