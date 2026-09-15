"""Admin write/read DTOs for editorial posts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from yupay.modules.blog.schemas import FaqOut, Locale, PostKind, PostStatus

_SLUG_PATTERN = r"^[a-z0-9][a-z0-9-]{1,94}[a-z0-9]$"


class TranslationIn(BaseModel):
    """One locale's copy. Upserted as a full array on PATCH (catalogue style)."""

    model_config = ConfigDict(extra="forbid")

    locale: Locale
    slug: str = Field(pattern=_SLUG_PATTERN, min_length=3, max_length=96)
    title: str = Field(min_length=1, max_length=200)
    excerpt: str = Field(default="", max_length=280)
    body_html: str = Field(default="", max_length=100_000)
    seo_title: str | None = Field(default=None, max_length=200)
    seo_description: str | None = Field(default=None, max_length=320)


class FaqIn(BaseModel):
    """Plain-text Q/A. No HTML — the body allowlist does not apply here."""

    model_config = ConfigDict(extra="forbid")

    locale: Locale
    sort_order: int = Field(default=0, ge=0, le=99)
    question: str = Field(min_length=1, max_length=280)
    answer: str = Field(min_length=1, max_length=2000)


class PostCreate(BaseModel):
    """Body of ``POST /admin/blog/posts``."""

    model_config = ConfigDict(extra="forbid")

    kind: PostKind
    #: Optional: a draft may not know yet what it sells (an imported article
    #: arrives without one). ``publish`` refuses until it is filled.
    primary_brand_id: str | None = None
    show_buy_card: bool = True
    pin_on_brand: bool = False
    cover_image_url: str | None = Field(default=None, max_length=512)
    event_starts_at: datetime | None = None
    event_ends_at: datetime | None = None
    translations: list[TranslationIn] = Field(min_length=1)
    related_brand_ids: list[str] = Field(default_factory=list)
    faqs: list[FaqIn] = Field(default_factory=list)


class PostUpdate(BaseModel):
    """Body of ``PATCH /admin/blog/posts/{id}``. Omitted fields stay as-is."""

    model_config = ConfigDict(extra="forbid")

    kind: PostKind | None = None
    primary_brand_id: str | None = None
    show_buy_card: bool | None = None
    pin_on_brand: bool | None = None
    cover_image_url: str | None = None
    event_starts_at: datetime | None = None
    event_ends_at: datetime | None = None
    translations: list[TranslationIn] | None = None
    related_brand_ids: list[str] | None = None
    faqs: list[FaqIn] | None = None


class TranslationOut(BaseModel):
    """Admin view of one locale row, including the sanitized body."""

    model_config = ConfigDict(from_attributes=True)

    locale: Locale
    slug: str
    title: str
    excerpt: str
    body_html: str
    seo_title: str | None
    seo_description: str | None


class AdminPostOut(BaseModel):
    """Full admin view of a post, including drafts."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: PostKind
    status: PostStatus
    primary_brand_id: str | None
    show_buy_card: bool
    pin_on_brand: bool
    cover_image_url: str | None
    event_starts_at: datetime | None
    event_ends_at: datetime | None
    published_at: datetime | None
    scheduled_for: datetime | None
    created_at: datetime
    updated_at: datetime
    translations: list[TranslationOut]
    related_brand_ids: list[str]
    faqs: list[FaqOut]


class AdminPostListOut(BaseModel):
    """Offset page used by the SPA list."""

    items: list[AdminPostOut]
    total: int


class ScheduleIn(BaseModel):
    """Body of ``POST /admin/blog/posts/{id}/schedule``."""

    model_config = ConfigDict(extra="forbid")

    scheduled_for: datetime


__all__ = [
    "AdminPostListOut",
    "AdminPostOut",
    "FaqIn",
    "PostCreate",
    "PostUpdate",
    "ScheduleIn",
    "TranslationIn",
    "TranslationOut",
]
