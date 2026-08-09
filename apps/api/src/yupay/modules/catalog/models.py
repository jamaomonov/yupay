"""SQLAlchemy ORM for the ``catalog`` module.

See ADR-0009 for the three-level model (Category → Brand → Product → SKU) and the
``Product.required_fields`` form schema.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yupay.core.db import Base


class Category(Base):
    """A flat top-level grouping (Games, Subscriptions, Gift cards, Crypto)."""

    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    icon: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    translations: Mapped[list[CategoryTranslation]] = relationship(
        back_populates="category",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class CategoryTranslation(Base):
    """Localised name + optional description for a category."""

    __tablename__ = "category_translations"

    category_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        PrimaryKeyConstraint("category_id", "locale", name="pk_category_translations"),
    )

    category: Mapped[Category] = relationship(back_populates="translations")


class Brand(Base):
    """A brand/game/service customers recognise (PUBG Mobile, Steam, Spotify)."""

    __tablename__ = "brands"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    category_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    )
    logo_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    hero_image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    accent_color: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # When true the brand stays visible but the storefront greys it out, shows a
    # "maintenance" badge and blocks purchases. ``active=False`` hides it entirely;
    # ``maintenance`` is the softer "temporarily unavailable" state.
    maintenance: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    category: Mapped[Category] = relationship(lazy="joined")
    translations: Mapped[list[BrandTranslation]] = relationship(
        back_populates="brand",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    products: Mapped[list[Product]] = relationship(
        back_populates="brand",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Product.sort_order",
    )
    faqs: Mapped[list[BrandFaq]] = relationship(
        back_populates="brand",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BrandFaq.sort_order",
    )


class BrandTranslation(Base):
    """Localised brand copy (name + short/long description)."""

    __tablename__ = "brand_translations"

    brand_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Longform "how to top up / supported regions / where to find your ID" guide,
    # rendered as an indexable prose section on the brand page.
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Short localized value-prop chips shown on the brand hero (e.g. Steam's
    # "0% комиссии", "Оплата в сумах"). NULL/absent -> no chips rendered.
    highlights: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (PrimaryKeyConstraint("brand_id", "locale", name="pk_brand_translations"),)

    brand: Mapped[Brand] = relationship(back_populates="translations")


class BrandFaq(Base):
    """A single FAQ entry attached to a brand.

    Rendered as an accordion on the brand page and emitted as ``FAQPage``
    structured data so the questions can win FAQ rich results in search.
    """

    __tablename__ = "brand_faqs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    brand_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
    )
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    brand: Mapped[Brand] = relationship(back_populates="faqs")
    translations: Mapped[list[BrandFaqTranslation]] = relationship(
        back_populates="faq",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class BrandFaqTranslation(Base):
    """Localised question/answer for a brand FAQ entry."""

    __tablename__ = "brand_faq_translations"

    brand_faq_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("brand_faqs.id", ondelete="CASCADE"),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    question: Mapped[str] = mapped_column(String(512), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("brand_faq_id", "locale", name="pk_brand_faq_translations"),
    )

    faq: Mapped[BrandFaq] = relationship(back_populates="translations")


class Product(Base):
    """One sellable concept within a :class:`Brand`.

    Examples:
        * PUBG Mobile → UC, Royal Pass, Skin Pack
        * Steam → Wallet Code, Gift Card
        * Spotify → Premium

    The product owns the form schema (:attr:`required_fields`) and the SKU set.
    """

    __tablename__ = "products"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    brand_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("brands.id", ondelete="RESTRICT"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    supplier_hint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    required_fields: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (CheckConstraint("kind IN ('top_up', 'voucher')", name="ck_products_kind"),)

    brand: Mapped[Brand] = relationship(back_populates="products", lazy="joined")
    translations: Mapped[list[ProductTranslation]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    skus: Mapped[list[Sku]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="Sku.sort_order",
    )


class ProductTranslation(Base):
    """Localised name + descriptions for a product."""

    __tablename__ = "product_translations"

    product_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(String(8), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (PrimaryKeyConstraint("product_id", "locale", name="pk_product_translations"),)

    product: Mapped[Product] = relationship(back_populates="translations")


class Sku(Base):
    """A specific sellable variant of a :class:`Product` (e.g. "60 UC TR")."""

    __tablename__ = "skus"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    product_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    sku_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    denomination: Mapped[str | None] = mapped_column(String(64), nullable=True)
    region: Mapped[str | None] = mapped_column(String(8), nullable=True)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    # Wholesale cost paid to the supplier, in USDT. Drives the bulk
    # UZS-price calculation (cost × current_fx_rate) and per-SKU
    # margin reporting. Nullable: legacy SKUs predate the column.
    cost_usdt: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    # Variable-amount SKUs (Steam wallet): the customer picks the amount, so
    # ``price_usd`` is not the price — it is computed at checkout from the
    # amount, the guarded FX rate and ``rate_multiplier``. The bounds are the
    # supplier's per-transaction limits.
    variable_amount: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    min_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    max_amount_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 6), nullable=True)
    # Margin: the customer-facing rate is the market rate times this.
    rate_multiplier: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # How many codes the supplier still holds. NULL means "not tracked" — every
    # game top-up, and voucher lines the supplier reports as unlimited. Zero
    # means out of stock. Refreshed by the scheduler; see ``in_stock``.
    supplier_stock: Mapped[int | None] = mapped_column(Integer, nullable=True)
    supplier_stock_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )

    __table_args__ = (
        CheckConstraint("price_usd > 0", name="ck_skus_price_positive"),
        CheckConstraint(
            "supplier_stock IS NULL OR supplier_stock >= 0",
            name="ck_skus_supplier_stock_non_negative",
        ),
        CheckConstraint(
            "cost_usdt IS NULL OR cost_usdt > 0",
            name="ck_skus_cost_usdt_positive",
        ),
        CheckConstraint(
            "NOT variable_amount OR ("
            " min_amount_usd IS NOT NULL AND max_amount_usd IS NOT NULL"
            " AND rate_multiplier IS NOT NULL AND min_amount_usd > 0"
            " AND max_amount_usd >= min_amount_usd AND rate_multiplier > 0)",
            name="ck_skus_variable_amount_complete",
        ),
    )

    product: Mapped[Product] = relationship(back_populates="skus")
    price_overrides: Mapped[list[SkuPrice]] = relationship(
        back_populates="sku",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def in_stock(self) -> bool:
        """Whether this variant can still be sold.

        The single place the NULL-means-untracked convention is interpreted, so
        the storefront DTO, the checkout guard and the admin all agree. Note it
        says nothing about ``active``: an operator switching a SKU off and a
        supplier running dry are different facts, and collapsing them would lose
        the operator's intent the next time stock is refreshed.
        """
        return self.supplier_stock is None or self.supplier_stock > 0


class SkuPrice(Base):
    """Optional per-currency price override that bypasses FX conversion."""

    __tablename__ = "sku_prices"

    sku_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("skus.id", ondelete="CASCADE"),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)

    __table_args__ = (
        PrimaryKeyConstraint("sku_id", "currency", name="pk_sku_prices"),
        CheckConstraint("price > 0", name="ck_sku_prices_positive"),
    )

    sku: Mapped[Sku] = relationship(back_populates="price_overrides")


__all__ = [
    "Brand",
    "BrandTranslation",
    "Category",
    "CategoryTranslation",
    "Product",
    "ProductTranslation",
    "Sku",
    "SkuPrice",
]
