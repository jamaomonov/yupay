"""Seed the catalog with a starter set following the 3-level structure (ADR-0009).

Idempotent — re-running matches by ``slug`` / ``sku_code`` and updates in place.
Run via ``docker compose exec api python -m yupay.scripts.seed_catalog``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from yupay.core.db import get_session_factory
from yupay.core.ids import new_id
from yupay.modules.catalog.models import (
    Brand,
    BrandTranslation,
    Category,
    CategoryTranslation,
    Product,
    ProductTranslation,
    Sku,
)


@dataclass
class TranslationSpec:
    locale: str
    name: str
    description: str | None = None
    short_description: str | None = None


@dataclass
class SkuSpec:
    sku_code: str
    denomination: str
    region: str | None
    price_usd: Decimal
    sort_order: int = 0


@dataclass
class ProductSpec:
    slug: str
    kind: str  # 'top_up' | 'voucher'
    supplier_hint: str | None
    image_url: str | None
    sort_order: int
    required_fields: list[dict[str, Any]]
    translations: list[TranslationSpec]
    skus: list[SkuSpec] = field(default_factory=list)


@dataclass
class BrandSpec:
    slug: str
    category_slug: str
    logo_url: str | None
    hero_image_url: str | None
    accent_color: str | None
    sort_order: int
    translations: list[TranslationSpec]
    products: list[ProductSpec] = field(default_factory=list)


@dataclass
class CategorySpec:
    slug: str
    icon: str | None
    sort_order: int
    translations: list[TranslationSpec]


# ---------- form-field presets ----------


def _player_id_field(*, label_ru: str = "ID игрока") -> dict[str, Any]:
    return {
        "key": "player_id",
        "label": {"ru": label_ru, "en": "Player ID", "uz": "Oʻyinchi ID"},
        "type": "text",
        "required": True,
        "pattern": "^[0-9]{6,15}$",
        "placeholder": {"ru": "12345678", "en": "12345678", "uz": "12345678"},
    }


def _server_field(options: list[tuple[str, str, str, str]]) -> dict[str, Any]:
    """``options`` items are ``(value, ru, en, uz)``."""
    return {
        "key": "server",
        "label": {"ru": "Сервер", "en": "Server", "uz": "Server"},
        "type": "select",
        "required": True,
        "options": [
            {"value": v, "label": {"ru": ru, "en": en, "uz": uz}} for (v, ru, en, uz) in options
        ],
    }


def _email_field() -> dict[str, Any]:
    return {
        "key": "account_email",
        "label": {"ru": "Email аккаунта", "en": "Account email", "uz": "Hisob email"},
        "type": "email",
        "required": True,
    }


def _wallet_address_field() -> dict[str, Any]:
    return {
        "key": "wallet_address",
        "label": {"ru": "Адрес кошелька", "en": "Wallet address", "uz": "Hamyon manzili"},
        "type": "text",
        "required": True,
        "pattern": "^T[A-Za-z0-9]{33}$",
        "help_text": {
            "ru": "USDT TRC-20 адрес (начинается с T)",
            "en": "USDT TRC-20 address (starts with T)",
            "uz": "USDT TRC-20 manzili (T bilan boshlanadi)",
        },
    }


CATEGORIES: list[CategorySpec] = [
    CategorySpec(
        slug="games",
        icon="gamepad",
        sort_order=10,
        translations=[
            TranslationSpec("ru", "Игры", "Пополнение игровых аккаунтов"),
            TranslationSpec("en", "Games", "Top up your game accounts"),
            TranslationSpec("uz", "Oʻyinlar", "Oʻyin hisoblarini toʻldirish"),
        ],
    ),
    CategorySpec(
        slug="subscriptions",
        icon="play",
        sort_order=20,
        translations=[
            TranslationSpec("ru", "Подписки", "Музыка, фильмы, сервисы"),
            TranslationSpec("en", "Subscriptions", "Music, movies, services"),
            TranslationSpec("uz", "Obunalar", "Musiqa, filmlar, xizmatlar"),
        ],
    ),
    CategorySpec(
        slug="gift-cards",
        icon="gift",
        sort_order=30,
        translations=[
            TranslationSpec("ru", "Подарочные карты", "Apple, Google Play, Amazon"),
            TranslationSpec("en", "Gift cards", "Apple, Google Play, Amazon"),
            TranslationSpec("uz", "Sovgʻa kartalari", "Apple, Google Play, Amazon"),
        ],
    ),
    CategorySpec(
        slug="crypto",
        icon="coins",
        sort_order=40,
        translations=[
            TranslationSpec("ru", "Криптовалюта", "Покупка USDT и других монет"),
            TranslationSpec("en", "Crypto", "Buy USDT and other coins"),
            TranslationSpec("uz", "Kriptovalyuta", "USDT va boshqa tangalar"),
        ],
    ),
]


BRANDS: list[BrandSpec] = [
    BrandSpec(
        slug="pubg-mobile",
        category_slug="games",
        logo_url="https://cdn.yupay.uz/brands/pubg-mobile.png",
        hero_image_url="https://cdn.yupay.uz/brands/pubg-mobile-hero.jpg",
        accent_color="#F2A900",
        sort_order=10,
        translations=[
            TranslationSpec(
                "ru",
                "PUBG Mobile",
                short_description="Пополнение UC, Royal Pass и косметика",
            ),
            TranslationSpec(
                "en",
                "PUBG Mobile",
                short_description="UC top-up, Royal Pass and cosmetics",
            ),
            TranslationSpec(
                "uz",
                "PUBG Mobile",
                short_description="UC toʻldirish, Royal Pass va kosmetika",
            ),
        ],
        products=[
            ProductSpec(
                slug="pubg-uc",
                kind="top_up",
                supplier_hint="codashop",
                image_url="https://cdn.yupay.uz/products/pubg-uc.png",
                sort_order=10,
                required_fields=[
                    _player_id_field(),
                    _server_field(
                        [
                            ("as", "Азия", "Asia", "Osiyo"),
                            ("eu", "Европа", "Europe", "Yevropa"),
                            ("na", "Сев. Америка", "North America", "Shimoliy Amerika"),
                            ("kr", "Корея/Япония", "Korea/Japan", "Koreya/Yaponiya"),
                        ]
                    ),
                ],
                translations=[
                    TranslationSpec("ru", "UC", short_description="Игровая валюта PUBG Mobile"),
                    TranslationSpec("en", "UC", short_description="PUBG Mobile in-game currency"),
                    TranslationSpec("uz", "UC", short_description="PUBG Mobile oʻyin valyutasi"),
                ],
                skus=[
                    SkuSpec("pubg-uc-60-tr", "60 UC", "TR", Decimal("0.85"), 10),
                    SkuSpec("pubg-uc-60-as", "60 UC", "AS", Decimal("0.99"), 11),
                    SkuSpec("pubg-uc-300-tr", "300 UC", "TR", Decimal("4.20"), 20),
                    SkuSpec("pubg-uc-300-as", "300 UC", "AS", Decimal("4.99"), 21),
                    SkuSpec("pubg-uc-660-tr", "660 UC", "TR", Decimal("8.50"), 30),
                    SkuSpec("pubg-uc-1800-tr", "1800 UC", "TR", Decimal("22.50"), 40),
                ],
            ),
            ProductSpec(
                slug="pubg-royal-pass",
                kind="top_up",
                supplier_hint="codashop",
                image_url="https://cdn.yupay.uz/products/pubg-royal-pass.png",
                sort_order=20,
                required_fields=[
                    _player_id_field(),
                    _server_field(
                        [
                            ("as", "Азия", "Asia", "Osiyo"),
                            ("eu", "Европа", "Europe", "Yevropa"),
                            ("na", "Сев. Америка", "North America", "Shimoliy Amerika"),
                        ]
                    ),
                ],
                translations=[
                    TranslationSpec("ru", "Royal Pass", short_description="Боевой пропуск сезона"),
                    TranslationSpec("en", "Royal Pass", short_description="Season battle pass"),
                    TranslationSpec("uz", "Royal Pass", short_description="Mavsumiy jangovar pass"),
                ],
                skus=[
                    SkuSpec("pubg-rp-elite", "Elite Pass", None, Decimal("9.99"), 10),
                    SkuSpec("pubg-rp-elite-plus", "Elite Pass Plus", None, Decimal("24.99"), 20),
                ],
            ),
        ],
    ),
    BrandSpec(
        slug="steam",
        category_slug="games",
        logo_url="https://cdn.yupay.uz/brands/steam.png",
        hero_image_url=None,
        accent_color="#1B2838",
        sort_order=20,
        translations=[
            TranslationSpec("ru", "Steam", short_description="Steam Wallet и подарочные карты"),
            TranslationSpec("en", "Steam", short_description="Steam Wallet and gift cards"),
            TranslationSpec("uz", "Steam", short_description="Steam Wallet va sovgʻa kartalari"),
        ],
        products=[
            ProductSpec(
                slug="steam-wallet",
                kind="voucher",
                supplier_hint="kupikod",
                image_url="https://cdn.yupay.uz/products/steam-wallet.png",
                sort_order=10,
                required_fields=[],
                translations=[
                    TranslationSpec(
                        "ru",
                        "Steam Wallet",
                        short_description="Код пополнения кошелька Steam",
                    ),
                    TranslationSpec(
                        "en",
                        "Steam Wallet",
                        short_description="Steam Wallet top-up code",
                    ),
                    TranslationSpec(
                        "uz",
                        "Steam Wallet",
                        short_description="Steam Wallet toʻldirish kodi",
                    ),
                ],
                skus=[
                    SkuSpec("steam-wallet-100-ru", "100 RUB", "RU", Decimal("1.40"), 10),
                    SkuSpec("steam-wallet-500-ru", "500 RUB", "RU", Decimal("6.20"), 20),
                    SkuSpec("steam-wallet-1000-ru", "1000 RUB", "RU", Decimal("12.00"), 30),
                    SkuSpec("steam-wallet-25-us", "25 USD", "US", Decimal("26.50"), 40),
                ],
            ),
        ],
    ),
    BrandSpec(
        slug="spotify",
        category_slug="subscriptions",
        logo_url="https://cdn.yupay.uz/brands/spotify.png",
        hero_image_url=None,
        accent_color="#1DB954",
        sort_order=10,
        translations=[
            TranslationSpec("ru", "Spotify", short_description="Подписки Spotify Premium"),
            TranslationSpec("en", "Spotify", short_description="Spotify Premium subscriptions"),
            TranslationSpec("uz", "Spotify", short_description="Spotify Premium obunalari"),
        ],
        products=[
            ProductSpec(
                slug="spotify-premium",
                kind="voucher",
                supplier_hint="aggregator",
                image_url="https://cdn.yupay.uz/products/spotify-premium.png",
                sort_order=10,
                required_fields=[_email_field()],
                translations=[
                    TranslationSpec("ru", "Premium", short_description="Spotify Premium"),
                    TranslationSpec("en", "Premium", short_description="Spotify Premium"),
                    TranslationSpec("uz", "Premium", short_description="Spotify Premium"),
                ],
                skus=[
                    SkuSpec("spotify-1mo", "1 месяц", None, Decimal("4.99"), 10),
                    SkuSpec("spotify-3mo", "3 месяца", None, Decimal("13.99"), 20),
                    SkuSpec("spotify-12mo", "12 месяцев", None, Decimal("49.99"), 30),
                ],
            ),
        ],
    ),
    BrandSpec(
        slug="apple",
        category_slug="gift-cards",
        logo_url="https://cdn.yupay.uz/brands/apple.png",
        hero_image_url=None,
        accent_color="#000000",
        sort_order=10,
        translations=[
            TranslationSpec("ru", "Apple", short_description="Apple Gift Card"),
            TranslationSpec("en", "Apple", short_description="Apple Gift Card"),
            TranslationSpec("uz", "Apple", short_description="Apple Gift Card"),
        ],
        products=[
            ProductSpec(
                slug="apple-gift-card",
                kind="voucher",
                supplier_hint="kupikod",
                image_url="https://cdn.yupay.uz/products/apple-gift-card.png",
                sort_order=10,
                required_fields=[],
                translations=[
                    TranslationSpec(
                        "ru",
                        "Gift Card",
                        short_description="Подарочная карта Apple (US)",
                    ),
                    TranslationSpec(
                        "en",
                        "Gift Card",
                        short_description="Apple gift card (US region)",
                    ),
                    TranslationSpec(
                        "uz",
                        "Gift Card",
                        short_description="Apple sovgʻa kartasi (US)",
                    ),
                ],
                skus=[
                    SkuSpec("apple-25-us", "25 USD", "US", Decimal("26.50"), 10),
                    SkuSpec("apple-50-us", "50 USD", "US", Decimal("52.00"), 20),
                    SkuSpec("apple-100-us", "100 USD", "US", Decimal("103.00"), 30),
                ],
            ),
        ],
    ),
    BrandSpec(
        slug="usdt",
        category_slug="crypto",
        logo_url="https://cdn.yupay.uz/brands/usdt.png",
        hero_image_url=None,
        accent_color="#26A17B",
        sort_order=10,
        translations=[
            TranslationSpec("ru", "USDT", short_description="Стейблкоин Tether"),
            TranslationSpec("en", "USDT", short_description="Tether stablecoin"),
            TranslationSpec("uz", "USDT", short_description="Tether stablecoin"),
        ],
        products=[
            ProductSpec(
                slug="usdt-trc20",
                kind="top_up",
                supplier_hint="crypto-acquirer",
                image_url="https://cdn.yupay.uz/products/usdt-trc20.png",
                sort_order=10,
                required_fields=[_wallet_address_field()],
                translations=[
                    TranslationSpec("ru", "TRC-20", short_description="USDT в сети TRON"),
                    TranslationSpec("en", "TRC-20", short_description="USDT on TRON"),
                    TranslationSpec("uz", "TRC-20", short_description="TRON tarmogʻida USDT"),
                ],
                skus=[
                    SkuSpec("usdt-10", "10 USDT", None, Decimal("10.30"), 10),
                    SkuSpec("usdt-50", "50 USDT", None, Decimal("51.20"), 20),
                    SkuSpec("usdt-100", "100 USDT", None, Decimal("102.00"), 30),
                ],
            ),
        ],
    ),
]


async def _upsert_category(session, spec: CategorySpec) -> str:
    existing = (
        await session.execute(
            select(Category)
            .options(selectinload(Category.translations))
            .where(Category.slug == spec.slug)
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = Category(
            id=new_id(),
            slug=spec.slug,
            icon=spec.icon,
            sort_order=spec.sort_order,
            translations=[],
        )
        session.add(existing)
        await session.flush()
    else:
        existing.icon = spec.icon
        existing.sort_order = spec.sort_order
    translations = await existing.awaitable_attrs.translations
    by_locale = {t.locale: t for t in translations}
    for tr in spec.translations:
        row = by_locale.get(tr.locale)
        if row is None:
            session.add(
                CategoryTranslation(
                    category_id=existing.id,
                    locale=tr.locale,
                    name=tr.name,
                    description=tr.description,
                )
            )
        else:
            row.name = tr.name
            row.description = tr.description
    return existing.id


async def _upsert_brand(session, spec: BrandSpec, category_id: str) -> Brand:
    existing = (
        await session.execute(
            select(Brand)
            .options(
                selectinload(Brand.translations),
                selectinload(Brand.products).selectinload(Product.translations),
                selectinload(Brand.products).selectinload(Product.skus),
            )
            .where(Brand.slug == spec.slug)
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = Brand(
            id=new_id(),
            slug=spec.slug,
            category_id=category_id,
            logo_url=spec.logo_url,
            hero_image_url=spec.hero_image_url,
            accent_color=spec.accent_color,
            sort_order=spec.sort_order,
            translations=[],
            products=[],
        )
        session.add(existing)
        await session.flush()
    else:
        existing.category_id = category_id
        existing.logo_url = spec.logo_url
        existing.hero_image_url = spec.hero_image_url
        existing.accent_color = spec.accent_color
        existing.sort_order = spec.sort_order

    translations = await existing.awaitable_attrs.translations
    by_locale = {t.locale: t for t in translations}
    for tr in spec.translations:
        row = by_locale.get(tr.locale)
        if row is None:
            session.add(
                BrandTranslation(
                    brand_id=existing.id,
                    locale=tr.locale,
                    name=tr.name,
                    short_description=tr.short_description,
                    description=tr.description,
                )
            )
        else:
            row.name = tr.name
            row.short_description = tr.short_description
            row.description = tr.description
    return existing


async def _upsert_product(session, spec: ProductSpec, brand: Brand) -> None:
    product = (
        await session.execute(
            select(Product)
            .options(
                selectinload(Product.translations),
                selectinload(Product.skus),
            )
            .where(Product.slug == spec.slug)
        )
    ).scalar_one_or_none()
    if product is None:
        product = Product(
            id=new_id(),
            slug=spec.slug,
            brand_id=brand.id,
            kind=spec.kind,
            supplier_hint=spec.supplier_hint,
            image_url=spec.image_url,
            sort_order=spec.sort_order,
            required_fields=spec.required_fields,
            translations=[],
            skus=[],
        )
        session.add(product)
        await session.flush()
    else:
        product.brand_id = brand.id
        product.kind = spec.kind
        product.supplier_hint = spec.supplier_hint
        product.image_url = spec.image_url
        product.sort_order = spec.sort_order
        product.required_fields = spec.required_fields

    translations = await product.awaitable_attrs.translations
    by_locale = {t.locale: t for t in translations}
    for tr in spec.translations:
        row = by_locale.get(tr.locale)
        if row is None:
            session.add(
                ProductTranslation(
                    product_id=product.id,
                    locale=tr.locale,
                    name=tr.name,
                    short_description=tr.short_description,
                    description=tr.description,
                )
            )
        else:
            row.name = tr.name
            row.short_description = tr.short_description
            row.description = tr.description

    skus = await product.awaitable_attrs.skus
    existing_skus = {s.sku_code: s for s in skus}
    for sspec in spec.skus:
        row = existing_skus.get(sspec.sku_code)
        if row is None:
            session.add(
                Sku(
                    id=new_id(),
                    product_id=product.id,
                    sku_code=sspec.sku_code,
                    denomination=sspec.denomination,
                    region=sspec.region,
                    price_usd=sspec.price_usd,
                    sort_order=sspec.sort_order,
                )
            )
        else:
            row.denomination = sspec.denomination
            row.region = sspec.region
            row.price_usd = sspec.price_usd
            row.sort_order = sspec.sort_order


async def seed() -> None:
    """Apply the seed set idempotently."""
    factory = get_session_factory()
    async with factory() as session:
        category_ids: dict[str, str] = {}
        for cspec in CATEGORIES:
            category_ids[cspec.slug] = await _upsert_category(session, cspec)
        await session.flush()

        for bspec in BRANDS:
            cat_id = category_ids[bspec.category_slug]
            brand = await _upsert_brand(session, bspec, cat_id)
            for pspec in bspec.products:
                await _upsert_product(session, pspec, brand)

        await session.commit()

    print(
        f"[seed_catalog] {len(CATEGORIES)} categories, "
        f"{len(BRANDS)} brands, "
        f"{sum(len(b.products) for b in BRANDS)} products, "
        f"{sum(len(p.skus) for b in BRANDS for p in b.products)} SKUs"
    )


def main() -> None:
    """Entry point for ``python -m yupay.scripts.seed_catalog``."""
    asyncio.run(seed())


if __name__ == "__main__":
    main()
