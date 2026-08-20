"""Seed the catalog with the curated 6-game CIS catalog (ADR-0009) + G2B supplier mappings.

Idempotent — re-running matches by ``slug`` / ``sku_code`` and updates in place.
Run via ``docker compose exec api python -m yupay.scripts.seed_catalog``.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
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
from yupay.modules.integrations.models import SkuSupplierMapping
from yupay.modules.sourcing.models import SkuSourcingRule


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
    # ``None`` for variable-amount SKUs — the wholesale cost isn't a fixed
    # per-unit figure, so it's left unknown rather than a misleading
    # placeholder. Margin reporting already treats ``cost_usdt IS NULL`` as
    # "excluded from cost-based margin" (see ``stats/analytics.py``).
    cost_usdt: Decimal | None = None
    # G2B routing key. Empty for non-G2B SKUs (e.g. Steam) — the
    # mapping-upsert loop below skips any SKU without a ``g2b_game_code``.
    g2b_game_code: str = ""
    g2b_variant: str = ""
    sort_order: int = 0
    # Variable-amount SKUs (Steam wallet): the customer picks the amount at
    # checkout, so ``price_usd`` above is an unused placeholder that only
    # satisfies the ``ck_skus_price_positive`` CHECK. See ``Sku.variable_amount``
    # and the ``ck_skus_variable_amount_complete`` CHECK for the invariant these
    # three fields must jointly satisfy when ``variable_amount`` is set.
    variable_amount: bool = False
    min_amount_usd: Decimal | None = None
    max_amount_usd: Decimal | None = None
    rate_multiplier: Decimal | None = None


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


def _player_id_field(
    *, label_ru: str = "ID игрока", check: dict[str, Any] | None = None
) -> dict[str, Any]:
    field: dict[str, Any] = {
        "key": "player_id",
        "label": {"ru": label_ru, "en": "Player ID", "uz": "Oʻyinchi ID"},
        "type": "text",
        "required": True,
        "pattern": "^[0-9]{6,20}$",
        "placeholder": {"ru": "12345678", "en": "12345678", "uz": "12345678"},
    }
    if check is not None:
        field["check"] = check
    return field


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


CATEGORIES: list[CategorySpec] = [
    CategorySpec(
        slug="games",
        icon="gamepad-2",
        sort_order=0,
        translations=[
            TranslationSpec("ru", "Игры"),
            TranslationSpec("en", "Games"),
            TranslationSpec("uz", "Oʻyinlar"),
        ],
    ),
]


# ---------- G2B catalogue snapshot ----------
#
# Auto-generated snapshot of the live G2B catalogue (currency + passes/subscriptions
# only; packs already excluded). Committed and embedded — the seed does NOT fetch G2B
# at runtime. Shape: ``{ game_code: { bucket: [ (g2b_name, cost_str), ... ] } }``, where
# ``bucket`` is one of ``"currency" | "pass" | "sub"``.
CATALOG_SNAPSHOT: dict[str, dict[str, list[tuple[str, str]]]] = {
    "pubgm": {
        "sub": [
            ("Prime (1 Month)", "0.88"),
            ("Prime (3 Months)", "2.64"),
            ("Prime (6 Months)", "5.28"),
            ("Prime Plus (1 Month)", "8.8"),
            ("Prime (12 Months)", "10.56"),
            ("Prime Plus (3 Months)", "26.4"),
            ("Prime Plus (6 Months)", "52"),
            ("Prime Plus (12 Months)", "105"),
        ],
        "currency": [
            ("60", "0.89"),
            ("325", "4.45"),
            ("660", "8.9"),
            ("985", "13.5"),
            ("1320", "18"),
            ("1800", "22.25"),
            ("2460", "31.5"),
            ("3850", "44.5"),
            ("5650", "67.5"),
            ("8100", "90.5"),
            ("11950", "135"),
            ("16200", "178"),
        ],
        "pass": [
            ("Elite Pass LV1-50", "5.3"),
            ("Elite Pass LV1-100", "10.692"),
            ("Elite Pass Plus LV1-100", "26.553"),
        ],
    },
    "freefire_cis": {
        "currency": [
            ("110", "0.82"),
            ("341", "2.47"),
            ("572", "4.02"),
            ("1166", "8.07"),
            ("2398", "16.14"),
            ("6160", "40.9"),
        ],
        "sub": [
            ("Weekly Membership", "1.61"),
            ("Monthly Membership", "5.81"),
        ],
    },
    "deltaforce": {
        "currency": [
            ("18", "0.235"),
            ("30", "0.388"),
            ("60", "0.785"),
            ("320", "3.937"),
            ("460", "5.722"),
            ("750", "7.895"),
            ("1480", "15.779"),
            ("1980", "19.717"),
            ("3950", "39.443"),
            ("8100", "78.887"),
            ("16200", "157.774"),
            ("24300", "236.66"),
        ],
        "pass": [
            ("Season Pass Warfare Special", "4.274"),
            ("Season Pass Operations Special", "4.274"),
            ("Season Pass Delta Force Deluxe", "5.916"),
            ("Pass Upgrade Level 20", "6.304"),
            ("Pass Upgrade Level 10", "10.516"),
            ("Pass Upgrade Level 30", "31.487"),
            ("Pass Upgrade Level 40", "41.749"),
            ("Pass Upgrade Level 60", "62.251"),
            ("Pass Upgrade Level 80", "82.396"),
        ],
    },
    "genshin": {
        "currency": [
            ("60", "1"),
            ("330", "5"),
            ("1090", "15"),
            ("2240", "30"),
            ("3880", "50"),
            ("8080", "100"),
        ],
        "sub": [
            ("Blessing", "5"),
        ],
    },
    "arena_breakout": {
        "currency": [
            ("66", "0.796"),
            ("335", "4.029"),
            ("675", "8.068"),
            ("1690", "20.155"),
            ("3400", "40.372"),
            ("6820", "82.192"),
            ("13640", "164.393"),
            ("20460", "246.585"),
        ],
        "pass": [
            ("Monthly Advanced Battle Pass Activation Pass", "0.877"),
            ("Monthly Premium Battle Pass Activation Pass", "3.529"),
            ("Quarterly Premium Battle Pass Bundle Activation Pass Bundle", "10.618"),
        ],
    },
    "arena_breakout_infinite": {
        "currency": [
            ("100", "0.989"),
            ("500", "4.937"),
            ("1000", "9.598"),
            ("2500", "23.837"),
            ("5000", "47.542"),
            ("10000", "94.962"),
        ],
        "pass": [
            ("Advanced Battle Pass Activation Card", "4.998"),
            ("Premium Battle Pass Activation Card", "15.004"),
        ],
    },
}


# ---------- game metadata → BRANDS builder ----------


def _tr(
    name_ru: str, name_en: str | None = None, name_uz: str | None = None
) -> list[TranslationSpec]:
    """Build ru/en/uz ``TranslationSpec``s for a product name.

    ``name_en``/``name_uz`` default to ``name_ru`` when the same string is used in all
    three locales (e.g. "UC", "Bonds", "Season Pass").
    """
    return [
        TranslationSpec("ru", name_ru),
        TranslationSpec("en", name_en if name_en is not None else name_ru),
        TranslationSpec("uz", name_uz if name_uz is not None else name_ru),
    ]


@dataclass
class ProductMeta:
    slug: str
    game_code: str  # CATALOG_SNAPSHOT top-level key
    bucket: str  # "currency" | "pass" | "sub"
    unit: str | None  # appended to the denomination for "currency" bucket SKUs
    translations: list[TranslationSpec]


@dataclass
class GameMeta:
    brand_slug: str
    name: str  # same string used for ru/en/uz brand translations
    required_fields: list[dict[str, Any]]
    products: list[ProductMeta]


GAME_META: list[GameMeta] = [
    GameMeta(
        brand_slug="pubg-mobile",
        name="PUBG Mobile",
        required_fields=[_player_id_field(check={"provider": "g2b"})],
        products=[
            ProductMeta("pubg-uc", "pubgm", "currency", "UC", _tr("UC")),
            ProductMeta("pubg-prime", "pubgm", "sub", None, _tr("Prime")),
            ProductMeta("pubg-royal-pass", "pubgm", "pass", None, _tr("Royal Pass")),
        ],
    ),
    GameMeta(
        brand_slug="free-fire",
        name="Free Fire",
        # `freefire_cis` used to rubber-stamp any id (ADR-0031); re-probed
        # 2026-08-20 and it now answers "invalid" for a bogus id like every
        # other G2B title, so the check is safe to enable.
        required_fields=[_player_id_field(check={"provider": "g2b"})],
        products=[
            ProductMeta(
                "free-fire-diamonds",
                "freefire_cis",
                "currency",
                "Diamonds",
                _tr("Алмазы", "Diamonds", "Olmoslar"),
            ),
            ProductMeta(
                "free-fire-membership",
                "freefire_cis",
                "sub",
                None,
                _tr("Подписка", "Membership", "Obuna"),
            ),
        ],
    ),
    GameMeta(
        brand_slug="delta-force",
        name="Delta Force",
        required_fields=[_player_id_field(check={"provider": "g2b"})],
        products=[
            ProductMeta(
                "delta-force-coins", "deltaforce", "currency", "Delta Coins", _tr("Delta Coins")
            ),
            ProductMeta("delta-force-season-pass", "deltaforce", "pass", None, _tr("Season Pass")),
        ],
    ),
    GameMeta(
        brand_slug="genshin-impact",
        name="Genshin Impact",
        # No G2B validation for Genshin; server selection is required alongside the UID.
        required_fields=[
            _player_id_field(label_ru="UID"),
            _server_field(
                [
                    ("os_usa", "Америка", "America", "Amerika"),
                    ("os_euro", "Европа", "Europe", "Yevropa"),
                    ("os_asia", "Азия", "Asia", "Osiyo"),
                    ("os_cht", "TW/HK/MO", "TW/HK/MO", "TW/HK/MO"),
                ]
            ),
        ],
        products=[
            ProductMeta(
                "genshin-crystals",
                "genshin",
                "currency",
                "Genesis Crystals",
                _tr("Кристаллы Сотворения", "Genesis Crystals", "Genesis Crystals"),
            ),
            ProductMeta(
                "genshin-welkin",
                "genshin",
                "sub",
                None,
                _tr(
                    "Благословение полой луны",
                    "Blessing of the Welkin Moon",
                    "Welkin Moon",
                ),
            ),
        ],
    ),
    GameMeta(
        brand_slug="arena-breakout",
        name="Arena Breakout",
        required_fields=[_player_id_field(check={"provider": "g2b"})],
        products=[
            ProductMeta(
                "arena-breakout-bonds", "arena_breakout", "currency", "Bonds", _tr("Bonds")
            ),
            ProductMeta(
                "arena-breakout-battle-pass", "arena_breakout", "pass", None, _tr("Battle Pass")
            ),
        ],
    ),
    GameMeta(
        brand_slug="arena-breakout-infinite",
        name="Arena Breakout: Infinite",
        required_fields=[_player_id_field(check={"provider": "g2b"})],
        products=[
            ProductMeta(
                "arena-breakout-infinite-coins",
                "arena_breakout_infinite",
                "currency",
                "Coins",
                _tr("Coins"),
            ),
            ProductMeta(
                "arena-breakout-infinite-battle-pass",
                "arena_breakout_infinite",
                "pass",
                None,
                _tr("Battle Pass"),
            ),
        ],
    ),
]


def _slugify(name: str) -> str:
    """Lowercase ``name`` and collapse runs of non-alphanumerics into single dashes.

    E.g. ``"Prime (1 Month)"`` → ``"prime-1-month"``, ``"60"`` → ``"60"``.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _sku_code(game_code: str, g2b_name: str) -> str:
    """Stable, unique sku_code that fits the 64-char column.

    Short names read cleanly (``pubgm-60``); long catalogue names (e.g. Arena
    Breakout's "Quarterly Premium Battle Pass Bundle …") overflow 64 chars, so
    the slug is truncated and a short deterministic hash of the full name is
    appended to preserve uniqueness and idempotency.
    """
    code = f"{game_code}-{_slugify(g2b_name)}"
    if len(code) <= 64:
        return code
    digest = hashlib.sha256(g2b_name.encode("utf-8")).hexdigest()[:8]
    keep = 64 - len(game_code) - 2 - len(digest)  # game_code + '-' + slug + '-' + digest
    return f"{game_code}-{_slugify(g2b_name)[:keep]}-{digest}"


def _build_skus(game_code: str, bucket: str, unit: str | None) -> list[SkuSpec]:
    """Generate one ``SkuSpec`` per ``(g2b_name, cost_str)`` pair in the snapshot bucket."""
    items = CATALOG_SNAPSHOT[game_code][bucket]
    skus: list[SkuSpec] = []
    for i, (g2b_name, cost_str) in enumerate(items):
        cost = Decimal(cost_str)
        price_usd = (cost * Decimal("1.20")).quantize(Decimal("0.01"))
        denomination = f"{g2b_name} {unit}" if bucket == "currency" else g2b_name
        skus.append(
            SkuSpec(
                sku_code=_sku_code(game_code, g2b_name),
                denomination=denomination,
                region=None,
                price_usd=price_usd,
                cost_usdt=cost,
                g2b_game_code=game_code,
                g2b_variant=g2b_name,
                sort_order=i,
            )
        )
    return skus


def _build_brands() -> list[BrandSpec]:
    """Build ``BRANDS`` from ``GAME_META`` + ``CATALOG_SNAPSHOT``. Pure and deterministic."""
    brands: list[BrandSpec] = []
    for bi, game in enumerate(GAME_META):
        products = [
            ProductSpec(
                slug=pmeta.slug,
                kind="top_up",
                supplier_hint="g2b",
                image_url=None,
                sort_order=pi,
                required_fields=game.required_fields,
                translations=pmeta.translations,
                skus=_build_skus(pmeta.game_code, pmeta.bucket, pmeta.unit),
            )
            for pi, pmeta in enumerate(game.products)
        ]
        brands.append(
            BrandSpec(
                slug=game.brand_slug,
                category_slug="games",
                logo_url=None,
                hero_image_url=None,
                accent_color=None,
                sort_order=bi,
                translations=[
                    TranslationSpec("ru", game.name),
                    TranslationSpec("en", game.name),
                    TranslationSpec("uz", game.name),
                ],
                products=products,
            )
        )
    return brands


# ---------- Steam wallet top-up (Waxpeer, not G2B) ----------
#
# Not part of ``GAME_META``/``CATALOG_SNAPSHOT``: Steam has one variable-amount
# SKU with no G2B mapping at all. It is routed to Waxpeer via a
# ``SkuSourcingRule`` (mode="force_supplier"), not a ``SkuSupplierMapping`` —
# ``SkuSupplierMapping.kind`` only allows ``'voucher'``/``'game'`` and
# ``WaxpeerFulfiller`` reads ``steam_login`` straight out of the order item's
# ``fulfillment_data``, never a mapping row. See the mapping-upsert loop in
# ``_upsert_product`` below, which skips SKUs with no ``g2b_game_code`` and
# creates/updates the sourcing rule for them instead.

_STEAM_LOGIN_FIELD: dict[str, Any] = {
    "key": "steam_login",
    "label": {"ru": "Логин Steam", "en": "Steam login", "uz": "Steam login"},
    "type": "text",
    "required": True,
    "pattern": r"^[A-Za-z0-9_-]{3,64}$",
    "check": {"provider": "waxpeer"},
}

_STEAM_BRAND = BrandSpec(
    slug="steam",
    category_slug="games",
    logo_url=None,
    hero_image_url=None,
    accent_color=None,
    sort_order=len(GAME_META),
    translations=[
        TranslationSpec("ru", "Steam"),
        TranslationSpec("en", "Steam"),
        TranslationSpec("uz", "Steam"),
    ],
    products=[
        ProductSpec(
            slug="steam-wallet",
            kind="top_up",
            supplier_hint="waxpeer",
            image_url=None,
            sort_order=0,
            required_fields=[_STEAM_LOGIN_FIELD],
            translations=_tr("Пополнение кошелька Steam", "Steam Wallet", "Steam hamyoni"),
            skus=[
                SkuSpec(
                    sku_code="steam-wallet-usd",
                    denomination="Любая сумма",
                    region=None,
                    price_usd=Decimal("1"),
                    sort_order=0,
                    variable_amount=True,
                    min_amount_usd=Decimal("1.00"),
                    max_amount_usd=Decimal("300.00"),
                    rate_multiplier=Decimal("1.0800"),
                ),
            ],
        ),
    ],
)


def _assert_unique_sku_codes(brands: list[BrandSpec]) -> None:
    seen: set[str] = set()
    for b in brands:
        for p in b.products:
            for s in p.skus:
                if s.sku_code in seen:
                    raise AssertionError(f"Duplicate sku_code in seed data: {s.sku_code!r}")
                seen.add(s.sku_code)


BRANDS: list[BrandSpec] = [*_build_brands(), _STEAM_BRAND]
_assert_unique_sku_codes(BRANDS)


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
    sku_ids: list[tuple[str, SkuSpec]] = []
    for sspec in spec.skus:
        row = existing_skus.get(sspec.sku_code)
        if row is None:
            sku_id = new_id()
            session.add(
                Sku(
                    id=sku_id,
                    product_id=product.id,
                    sku_code=sspec.sku_code,
                    denomination=sspec.denomination,
                    region=sspec.region,
                    price_usd=sspec.price_usd,
                    cost_usdt=sspec.cost_usdt,
                    sort_order=sspec.sort_order,
                    variable_amount=sspec.variable_amount,
                    min_amount_usd=sspec.min_amount_usd,
                    max_amount_usd=sspec.max_amount_usd,
                    rate_multiplier=sspec.rate_multiplier,
                )
            )
        else:
            sku_id = row.id
            row.denomination = sspec.denomination
            row.region = sspec.region
            row.price_usd = sspec.price_usd
            row.cost_usdt = sspec.cost_usdt
            row.sort_order = sspec.sort_order
            row.variable_amount = sspec.variable_amount
            row.min_amount_usd = sspec.min_amount_usd
            row.max_amount_usd = sspec.max_amount_usd
            row.rate_multiplier = sspec.rate_multiplier
        sku_ids.append((sku_id, sspec))

    # SkuSupplierMapping.sku_id is a plain FK column, not a relationship, so SQLAlchemy
    # won't order the pending Sku inserts ahead of the mapping inserts for us — flush
    # explicitly so every sku_id referenced below is backed by a persisted row.
    await session.flush()

    for sku_id, sspec in sku_ids:
        if not sspec.g2b_game_code:
            # Not a G2B-sourced SKU (e.g. Steam) — no SkuSupplierMapping to write
            # (SkuSupplierMapping.kind only allows 'voucher'/'game'; Waxpeer isn't
            # routed through a mapping at all). Route it with a sourcing rule
            # instead, per the product's ``supplier_hint``.
            await _upsert_sourcing_rule(session, sku_id=sku_id, supplier_slug=spec.supplier_hint)
            continue

        mapping = (
            await session.execute(
                select(SkuSupplierMapping).where(
                    SkuSupplierMapping.sku_id == sku_id,
                    SkuSupplierMapping.supplier_slug == "g2b",
                )
            )
        ).scalar_one_or_none()
        if mapping is None:
            session.add(
                SkuSupplierMapping(
                    sku_id=sku_id,
                    supplier_slug="g2b",
                    kind="game",
                    external_product_id=sspec.g2b_game_code,
                    external_variant_id=sspec.g2b_variant,
                    quantity=1,
                    is_active=True,
                )
            )
        else:
            mapping.kind = "game"
            mapping.external_product_id = sspec.g2b_game_code
            mapping.external_variant_id = sspec.g2b_variant
            mapping.is_active = True


async def _upsert_sourcing_rule(session, *, sku_id: str, supplier_slug: str | None) -> None:
    """Force fulfilment to a specific supplier for SKUs with no supplier mapping.

    Used for non-G2B top-up SKUs (currently just Steam → Waxpeer). Mirrors
    ``yupay.modules.sourcing.service.set_rule`` but is written directly against
    the ORM, matching this file's existing upsert style (see the
    ``SkuSupplierMapping`` loop above) rather than going through the service,
    which requires an ``admin_id`` that doesn't make sense for seed data.
    """
    if not supplier_slug:
        return
    rule = (
        await session.execute(select(SkuSourcingRule).where(SkuSourcingRule.sku_id == sku_id))
    ).scalar_one_or_none()
    if rule is None:
        session.add(
            SkuSourcingRule(
                sku_id=sku_id,
                mode="force_supplier",
                supplier_slug=supplier_slug,
            )
        )
    else:
        rule.mode = "force_supplier"
        rule.supplier_slug = supplier_slug


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
