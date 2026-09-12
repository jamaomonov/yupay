"""Public read DTOs for the blog. Admin write models live in ``admin_schemas``."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PostKind = Literal["guide", "news", "update", "event"]
PostStatus = Literal["draft", "scheduled", "published", "archived"]
Locale = Literal["ru", "en", "uz"]


class BrandRefOut(BaseModel):
    """The primary catalogue brand the post converts toward."""

    slug: str
    name: str


class FaqOut(BaseModel):
    """A visible Q/A pair. Must match the on-page FAQ (GEO / ``FAQPage``)."""

    model_config = ConfigDict(from_attributes=True)

    locale: Locale
    sort_order: int
    question: str
    answer: str


class PostListItemOut(BaseModel):
    """One card on the public index or brand block. Never a draft."""

    id: str
    slug: str
    kind: PostKind
    title: str
    excerpt: str
    cover_image_url: str | None
    published_at: datetime | None
    updated_at: datetime
    primary_brand: BrandRefOut
    event_starts_at: datetime | None
    event_ends_at: datetime | None
    pin_on_brand: bool
    like_count: int = 0
    view_count: int = 0


class PostDetailOut(PostListItemOut):
    """A published translation, ready for the storefront article (M2)."""

    body_html: str
    seo_title: str | None = None
    seo_description: str | None = None
    show_buy_card: bool
    related_brand_slugs: list[str]
    faqs: list[FaqOut]
    locale_slugs: dict[str, str]


class EngagementOut(BaseModel):
    """Fresh like/view counts after a guest records a view or toggles a like."""

    liked: bool
    like_count: int
    view_count: int


class PostListOut(BaseModel):
    """A keyset page of :class:`PostListItemOut`."""

    items: list[PostListItemOut]
    next_cursor: str | None = None


class BrandBlockOut(BaseModel):
    """Pins plus latest published posts for ``/store/{brand}`` (M2)."""

    items: list[PostListItemOut] = Field(default_factory=list)


__all__ = [
    "BrandBlockOut",
    "BrandRefOut",
    "EngagementOut",
    "FaqOut",
    "Locale",
    "PostDetailOut",
    "PostKind",
    "PostListItemOut",
    "PostListOut",
    "PostStatus",
]
