"""SQLAlchemy ORM for the ``blog`` module.

A post is always bound to one catalogue brand (the conversion target) and
may mention extra brands. Copy lives per locale with no fallback bleed —
a missing ``uz`` row is omitted from ``uz``, not filled from ``ru``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from yupay.core.db import Base

POST_KINDS = ("guide", "news", "update", "event")
POST_STATUSES = ("draft", "scheduled", "published", "archived")
LOCALES = ("ru", "en", "uz")


class BlogPost(Base):
    """One editorial story, kind + lifecycle + the primary brand it sells."""

    __tablename__ = "blog_posts"
    # Bare CHECK suffixes: the metadata naming convention prepends
    # ``ck_blog_posts_``. A full name here would double the prefix.
    __table_args__ = (
        CheckConstraint(
            "kind IN ('guide', 'news', 'update', 'event')",
            name="kind_known",
        ),
        CheckConstraint(
            "status IN ('draft', 'scheduled', 'published', 'archived')",
            name="status_known",
        ),
        Index("ix_blog_posts_status_published", "status", "published_at"),
        Index(
            "ix_blog_posts_brand_status_published",
            "primary_brand_id",
            "status",
            "published_at",
        ),
        Index(
            "ix_blog_posts_brand_pinned",
            "primary_brand_id",
            postgresql_where=text("pin_on_brand AND status = 'published'"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default=text("'draft'"))
    primary_brand_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("brands.id", ondelete="RESTRICT"),
        nullable=False,
    )
    show_buy_card: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    pin_on_brand: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    cover_image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    event_starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    event_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    like_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    view_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    translations: Mapped[list[BlogPostTranslation]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    extra_brands: Mapped[list[BlogPostBrand]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    faqs: Mapped[list[BlogPostFaq]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="BlogPostFaq.sort_order",
    )


class BlogPostTranslation(Base):
    """Locale-specific slug, title and sanitized HTML body."""

    __tablename__ = "blog_post_translations"
    __table_args__ = (
        PrimaryKeyConstraint("post_id", "locale", name="pk_blog_post_translations"),
        CheckConstraint("locale IN ('ru', 'en', 'uz')", name="locale_known"),
        UniqueConstraint("locale", "slug", name="uq_blog_post_translations_locale_slug"),
    )

    post_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("blog_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(String(3), nullable=False)
    slug: Mapped[str] = mapped_column(String(96), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    excerpt: Mapped[str] = mapped_column(String(280), nullable=False, server_default=text("''"))
    body_html: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("''"))
    seo_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    seo_description: Mapped[str | None] = mapped_column(String(320), nullable=True)

    post: Mapped[BlogPost] = relationship(back_populates="translations")


class BlogPostBrand(Base):
    """An extra brand mentioned by a post. The primary brand is not duplicated."""

    __tablename__ = "blog_post_brands"
    __table_args__ = (PrimaryKeyConstraint("post_id", "brand_id", name="pk_blog_post_brands"),)

    post_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("blog_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    brand_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("brands.id", ondelete="RESTRICT"),
        nullable=False,
    )

    post: Mapped[BlogPost] = relationship(back_populates="extra_brands")


class BlogPostFaq(Base):
    """A visible Q/A pair that also feeds ``FAQPage`` JSON-LD (must match the page)."""

    __tablename__ = "blog_post_faqs"
    __table_args__ = (
        PrimaryKeyConstraint("id"),
        CheckConstraint("locale IN ('ru', 'en', 'uz')", name="locale_known"),
        UniqueConstraint(
            "post_id", "locale", "sort_order", name="uq_blog_post_faqs_post_locale_sort"
        ),
        Index("ix_blog_post_faqs_post_locale", "post_id", "locale"),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    post_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("blog_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    locale: Mapped[str] = mapped_column(String(3), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    question: Mapped[str] = mapped_column(String(280), nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)

    post: Mapped[BlogPost] = relationship(back_populates="faqs")


class BlogPostLike(Base):
    """One like from one anonymous reader. ``reader_hash`` is SHA-256 of a cookie."""

    __tablename__ = "blog_post_likes"
    __table_args__ = (PrimaryKeyConstraint("post_id", "reader_hash", name="pk_blog_post_likes"),)

    post_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("blog_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    reader_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class BlogPostView(Base):
    """First view from one anonymous reader. Repeat views do not increment."""

    __tablename__ = "blog_post_views"
    __table_args__ = (PrimaryKeyConstraint("post_id", "reader_hash", name="pk_blog_post_views"),)

    post_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("blog_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    reader_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class BlogIndexNowPing(Base):
    """One IndexNow batch for a publish or archive. The worker drains these."""

    __tablename__ = "blog_indexnow_pings"
    __table_args__ = (
        CheckConstraint("reason IN ('published', 'archived')", name="reason_known"),
        CheckConstraint(
            "status IN ('pending', 'done', 'skipped', 'failed')",
            name="status_known",
        ),
        Index(
            "ix_blog_indexnow_pings_pending",
            "created_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True)
    post_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("blog_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(String(16), nullable=False)
    urls: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=text("'pending'")
    )
    last_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
