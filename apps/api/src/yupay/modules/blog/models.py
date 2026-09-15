"""SQLAlchemy ORM for the ``blog`` module.

Anything a reader can reach is bound to one catalogue brand (the conversion
target) and may mention extra brands; a *draft* may not have one yet, which
is how an imported article lands before an editor has decided what it sells.
Copy lives per locale with no fallback bleed — a missing ``uz`` row is
omitted from ``uz``, not filled from ``ru``.
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
        # A draft may have no brand yet — an imported article arrives before
        # anyone has decided what it sells. Everything a reader can reach
        # must have one: every public query inner-joins ``brands`` through
        # this column, and they all filter to ``published``.
        CheckConstraint(
            "primary_brand_id IS NOT NULL OR status = 'draft'",
            name="brand_unless_draft",
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
    primary_brand_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("brands.id", ondelete="RESTRICT"),
        nullable=True,
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


class BlogImportedPost(Base):
    """What an external writer sent us, and what we made of it.

    One row per upstream article, keyed by the identifier *they* use. It
    exists to answer two questions on every re-sync: has the source changed
    since we last looked, and is our copy still the one we wrote? The second
    is what protects an editor's work — ``rendered_hash`` is the body we
    stored, so a body that no longer hashes to it has been edited by hand and
    the importer leaves it alone.
    """

    __tablename__ = "blog_imported_posts"
    __table_args__ = (
        PrimaryKeyConstraint("source", "external_id", name="pk_blog_imported_posts"),
        UniqueConstraint("post_id", name="uq_blog_imported_posts_post"),
        CheckConstraint("source IN ('bunzy')", name="source_known"),
    )

    source: Mapped[str] = mapped_column(String(16), nullable=False)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    post_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("blog_posts.id", ondelete="CASCADE"),
        nullable=False,
    )
    #: SHA-256 over the upstream fields we consume, so an unchanged article
    #: costs one comparison and no writes.
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: SHA-256 of the ``body_html`` we last wrote for this article.
    rendered_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    #: Last pass that saw the article upstream, changed or not.
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    #: Last pass that actually rewrote our copy.
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


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
