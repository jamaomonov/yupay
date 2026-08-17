"""Onboard Telegram Stars and Telegram Premium as two brands, fulfilled by G-Engine.

Run inside the api container (it needs the ``yupay`` package, the DB and
``GENGINE_API_KEY``):

    docker compose exec -T api python - < scripts/seed/2026-08-17_telegram_import.py

and on prod:

    docker compose -f docker-compose.prod.yml exec -T api python - \
        < scripts/seed/2026-08-17_telegram_import.py

Then apply the SEO pack: ``scripts/seed/telegram_seo.sql``.

Four things here are not like the earlier imports:

* **A third category.** Telegram is neither a game nor a gift card. It goes in
  ``subscriptions``, which is also where Spotify / YouTube Premium belong when
  their turn comes — the fulfilment registry already carries slugs for them.
* **Two brands, not one.** Stars and Premium share a logo and nothing else: one
  is a currency bought by the hundred, the other a subscription bought by the
  quarter. They have different buyers, different questions and different search
  terms, so they get separate brand pages rather than two tabs on one.
* **Stars are sold as fixed packages.** G-Engine's service 72 is ``unfixed`` —
  it takes a ``Quantity`` rather than a denomination. We could expose that as a
  Steam-style "type any amount" box, but a shelf of packages is what buyers here
  expect (and what every local competitor shows). The star count therefore lives
  on the mapping's ``quantity``, which is exactly what the adapter forwards as
  ``Quantity``.
* **50 Stars is a floor, not a choice.** Telegram itself refuses smaller
  transfers, so no package below it exists and none can be added.

**Costs are read live, never baked in.** Stars are priced off
``unfixed_details.rate`` (Stars per USD, 64.705882 at the time of writing → about
$0.01545 each); Premium off its denomination prices. A service that does not
resolve aborts the import rather than leaving a mapping that cannot be fulfilled.
``margin_percent`` is written on every SKU so the hourly price refresh re-derives
``price_usd`` when G-Engine moves — for Stars, whose rate floats, that matters
more than for anything else in the catalog.

Idempotent: category, brands and products are reused when present, and existing
``sku_code``s are skipped.
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
from yupay.modules.catalog.models import Brand, Category, Product, Sku
from yupay.modules.fulfillment.suppliers.gengine_client import GEngineClient
from yupay.modules.integrations.service import MappingUpsert, upsert_mapping

CATEGORY_SLUG = "subscriptions"
MARGIN_PERCENT = Decimal("20")
ADMIN_ID = "00000000-0000-7000-8000-000000000001"

#: G-Engine service ids, verified against GET /recharge/services.
STARS_SERVICE_ID = 72
PREMIUM_SERVICE_ID = 79

CATEGORY_NAMES = {
    "ru": "Подписки и сервисы",
    "en": "Subscriptions & services",
    "uz": "Obunalar va xizmatlar",
}

#: Telegram usernames are 5–32 characters, start with a letter and hold only
#: letters, digits and underscores. The leading ``@`` is optional because half
#: of buyers paste it and half do not — G-Engine accepts either.
USERNAME_PATTERN = r"^@?[A-Za-z][A-Za-z0-9_]{4,31}$"

USERNAME_FIELD = cat_schemas.FormField(
    key="username",
    type="text",
    required=True,
    pattern=USERNAME_PATTERN,
    label={
        "ru": "Username в Telegram",
        "en": "Telegram username",
        "uz": "Telegram username",
    },
    placeholder={"ru": "@username", "en": "@username", "uz": "@username"},
    help_text={
        "ru": (
            "Откройте Telegram → Настройки → Имя пользователя. "
            "Пароль и код входа не нужны — мы ничего не спрашиваем, кроме username."
        ),
        "en": (
            "Open Telegram → Settings → Username. "
            "No password and no login code — the username is all we ask for."
        ),
        "uz": (
            "Telegram → Sozlamalar → Foydalanuvchi nomi boʻlimini oching. "
            "Parol ham, kirish kodi ham kerak emas — bizga faqat username kifoya."
        ),
    },
)

#: Star packages. Mirrors what local sellers list, starting at Telegram's own
#: 50-star floor. The number is both the SKU's denomination and the `Quantity`
#: the adapter sends.
STAR_PACKAGES = [50, 75, 100, 150, 250, 350, 500, 750, 1000, 1500, 2500]

#: Premium denominations, from GET /recharge/services (service 79).
PREMIUM_PLANS: list[tuple[str, int, dict[str, str]]] = [
    (
        "tg-premium-3m",
        738,
        {"ru": "3 месяца", "en": "3 months", "uz": "3 oy"},
    ),
    (
        "tg-premium-6m",
        739,
        {"ru": "6 месяцев", "en": "6 months", "uz": "6 oy"},
    ),
    (
        "tg-premium-12m",
        740,
        {"ru": "12 месяцев", "en": "12 months", "uz": "12 oy"},
    ),
]

BRANDS = {
    "telegram-stars": {"ru": "Telegram Stars", "en": "Telegram Stars", "uz": "Telegram Stars"},
    "telegram-premium": {
        "ru": "Telegram Premium",
        "en": "Telegram Premium",
        "uz": "Telegram Premium",
    },
}


def _sell_price(cost: Decimal) -> Decimal:
    """cost × (1 + margin), rounded to cents the same way import_game does."""
    return (cost * (Decimal(1) + MARGIN_PERCENT / Decimal(100))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


async def _ensure_category(session: Any) -> str:
    existing = (
        await session.execute(select(Category).where(Category.slug == CATEGORY_SLUG))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"category {CATEGORY_SLUG}: reusing {existing.id}")
        return str(existing.id)
    row = await catalog.create_category(
        session,
        cat_schemas.CategoryCreate(
            slug=CATEGORY_SLUG,
            # lucide name, matching "gamepad-2" for games and "gift" for cards.
            icon="badge-check",
            # After games and gift cards.
            sort_order=2,
            translations=[
                cat_schemas.CategoryTranslationIn(locale=loc, name=name)
                for loc, name in CATEGORY_NAMES.items()
            ],
        ),
    )
    print(f"category {CATEGORY_SLUG}: created {row.id}")
    return str(row.id)


async def _ensure_brand(session: Any, *, slug: str, names: dict[str, str], category_id: str) -> str:
    existing = (await session.execute(select(Brand).where(Brand.slug == slug))).scalar_one_or_none()
    if existing is not None:
        print(f"  brand {slug}: reusing {existing.id}")
        return str(existing.id)
    row = await catalog.create_brand(
        session,
        cat_schemas.BrandCreate(
            slug=slug,
            category_id=category_id,
            translations=[
                cat_schemas.TranslationIn(locale=loc, name=name) for loc, name in names.items()
            ],
        ),
    )
    print(f"  brand {slug}: created {row.id}")
    return str(row.id)


async def _ensure_product(session: Any, *, slug: str, names: dict[str, str], brand_id: str) -> str:
    existing = (
        await session.execute(select(Product).where(Product.slug == slug))
    ).scalar_one_or_none()
    if existing is not None:
        print(f"    product {slug}: reusing {existing.id}")
        return str(existing.id)
    row = await catalog.create_product(
        session,
        cat_schemas.ProductCreate(
            slug=slug,
            brand_id=brand_id,
            kind="top_up",
            supplier_hint="gengine",
            # One field, and it is not a secret: Telegram credits a public
            # @username. Nothing here can be used to sign in to an account.
            required_fields=[USERNAME_FIELD],
            translations=[
                cat_schemas.TranslationIn(locale=loc, name=name) for loc, name in names.items()
            ],
        ),
    )
    print(f"    product {slug}: created {row.id}")
    return str(row.id)


async def _existing_codes(session: Any, codes: list[str]) -> set[str]:
    rows = await session.execute(select(Sku.sku_code).where(Sku.sku_code.in_(codes)))
    return set(rows.scalars().all())


async def _fetch_service(client: GEngineClient, service_id: int) -> dict[str, Any]:
    """Return one service from the catalogue, or abort the import.

    A mapping to an id that does not resolve looks fine in the admin and fails
    only once a customer has paid.
    """
    for offset in (0, 100, 200):
        page = await client.list_recharge_services(limit=100, offset=offset)
        if not page:
            break
        for service in page:
            if service.get("id") == service_id:
                return service
    raise SystemExit(
        f"G-Engine service {service_id} does not resolve — refusing to create a "
        "mapping that cannot be fulfilled"
    )


async def _seed_stars(session: Any, *, client: GEngineClient, category_id: str) -> None:
    service = await _fetch_service(client, STARS_SERVICE_ID)
    details = service.get("unfixed_details") or {}
    rate = Decimal(str(details.get("rate") or 0))
    if rate <= 0:
        raise SystemExit(
            f"G-Engine service {STARS_SERVICE_ID} reports no usable rate "
            f"({details!r}) — cannot price Stars"
        )
    print(f"  stars: rate={rate} Stars per USD (${Decimal(1) / rate:.6f} each)")

    brand_id = await _ensure_brand(
        session, slug="telegram-stars", names=BRANDS["telegram-stars"], category_id=category_id
    )
    product_id = await _ensure_product(
        session,
        slug="telegram-stars",
        names=dict.fromkeys(("ru", "en", "uz"), "Stars"),
        brand_id=brand_id,
    )

    codes = [f"tg-stars-{n}" for n in STAR_PACKAGES]
    present = await _existing_codes(session, codes)

    for position, stars in enumerate(STAR_PACKAGES):
        sku_code = f"tg-stars-{stars}"
        if sku_code in present:
            print(f"      {sku_code}: exists — skipped")
            continue
        cost = (Decimal(stars) / rate).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        sku = await catalog.create_sku(
            session,
            cat_schemas.SkuCreate(
                product_id=product_id,
                sku_code=sku_code,
                denomination=f"{stars} Stars",
                price_usd=_sell_price(cost),
                cost_usdt=cost,
                margin_percent=MARGIN_PERCENT,
                sort_order=position,
            ),
        )
        await upsert_mapping(
            session,
            MappingUpsert(
                sku_id=sku.id,
                supplier_slug="gengine",
                kind="game",
                external_product_id=str(STARS_SERVICE_ID),
                # Unfixed service: no denomination exists. The star count rides
                # on `quantity`, which the adapter sends as the `Quantity` param.
                external_variant_id=None,
                quantity=stars,
                extra={},
                is_active=True,
                updated_by=ADMIN_ID,
            ),
        )
        print(f"      {sku_code}: cost={cost} price={_sell_price(cost)} quantity={stars}")


async def _seed_premium(session: Any, *, client: GEngineClient, category_id: str) -> None:
    service = await _fetch_service(client, PREMIUM_SERVICE_ID)
    prices = {
        int(d["id"]): Decimal(str(d.get("price") or 0)) for d in service.get("denominations") or []
    }
    print(f"  premium: denominations {sorted(prices)}")

    brand_id = await _ensure_brand(
        session, slug="telegram-premium", names=BRANDS["telegram-premium"], category_id=category_id
    )
    product_id = await _ensure_product(
        session,
        slug="telegram-premium",
        names={"ru": "Подписка", "en": "Subscription", "uz": "Obuna"},
        brand_id=brand_id,
    )

    present = await _existing_codes(session, [c for c, _, _ in PREMIUM_PLANS])

    for position, (sku_code, denom_id, labels) in enumerate(PREMIUM_PLANS):
        if sku_code in present:
            print(f"      {sku_code}: exists — skipped")
            continue
        cost = prices.get(denom_id, Decimal(0))
        if cost <= 0:
            raise SystemExit(
                f"G-Engine denomination {denom_id} for {sku_code} is missing or free "
                f"({cost}) — refusing to sell it at a guessed price"
            )
        sku = await catalog.create_sku(
            session,
            cat_schemas.SkuCreate(
                product_id=product_id,
                sku_code=sku_code,
                denomination=labels["ru"],
                price_usd=_sell_price(cost),
                cost_usdt=cost,
                margin_percent=MARGIN_PERCENT,
                sort_order=position,
            ),
        )
        await upsert_mapping(
            session,
            MappingUpsert(
                sku_id=sku.id,
                supplier_slug="gengine",
                kind="game",
                external_product_id=str(PREMIUM_SERVICE_ID),
                external_variant_id=str(denom_id),
                quantity=1,
                extra={},
                is_active=True,
                updated_by=ADMIN_ID,
            ),
        )
        print(f"      {sku_code}: denom={denom_id} cost={cost} price={_sell_price(cost)}")


async def main() -> None:
    settings = get_settings()
    if not settings.gengine_api_key:
        raise SystemExit("GENGINE_API_KEY is not set — the import needs it to read live prices")
    client = GEngineClient(
        api_key=settings.gengine_api_key,
        base_url=settings.gengine_base_url,
        timeout_seconds=settings.gengine_request_timeout_seconds,
    )

    async with get_session_factory()() as session:
        category_id = await _ensure_category(session)
        await _seed_stars(session, client=client, category_id=category_id)
        await _seed_premium(session, client=client, category_id=category_id)
        await session.commit()
        print("committed")


asyncio.run(main())
