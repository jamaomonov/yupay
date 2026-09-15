"""Read-only HTTP client for the Bunzy blog API.

One article a day is written for us on ``app.bunzy.io``; this pulls the
published ones so :mod:`bunzy_import` can file them as drafts. Read-only on
purpose — nothing here can change anything on their side, so the worst a
compromised response can do is refuse to parse.

The API key authenticates as our whole blog account. It is a server-side
credential: it lives in ``secrets/api.env``, it is read through
:func:`get_settings`, and it must never be handed to a browser. Nothing in
this module returns it, and the logger below never receives it.
"""

from __future__ import annotations

from typing import Any, Final

import httpx
from pydantic import BaseModel, ConfigDict, Field

from yupay.core.config import get_settings
from yupay.core.logging import get_logger

log = get_logger("yupay.blog.bunzy")

_TIMEOUT: Final = 15.0
_MAX_MARKDOWN_CHARS: Final = 80_000


class BunzyUnavailableError(Exception):
    """Bunzy answered with something we cannot use. Status only, never a body."""

    def __init__(self, status_code: int, path: str) -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(f"bunzy {path} -> http {status_code}")


class BunzyAuthor(BaseModel):
    """Byline. We have no author column; kept so the shape round-trips."""

    model_config = ConfigDict(extra="ignore")

    name: str = ""


class BunzyFaq(BaseModel):
    """One Q/A pair. Plain text both sides — it feeds ``blog_post_faqs``."""

    model_config = ConfigDict(extra="ignore")

    question: str
    answer: str


class BunzySeo(BaseModel):
    """The SEO block. ``jsonLd`` is ignored: we build our own from the row."""

    model_config = ConfigDict(extra="ignore")

    meta_title: str | None = Field(default=None, alias="metaTitle")
    meta_description: str | None = Field(default=None, alias="metaDescription")
    canonical_url: str | None = Field(default=None, alias="canonicalUrl")
    og_image: str | None = Field(default=None, alias="ogImage")
    focus_keyword: str | None = Field(default=None, alias="focusKeyword")


class BunzyLabels(BaseModel):
    """Section headings, already in the article's own language."""

    model_config = ConfigDict(extra="ignore")

    key_takeaways: str = Field(default="", alias="keyTakeaways")
    faq: str = Field(default="", alias="faq")


class BunzySummary(BaseModel):
    """A row of ``GET /posts``. ``slug`` is the only stable identifier given."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    slug: str
    title: str = ""
    updated_at: str | None = Field(default=None, alias="updatedAt")
    published_at: str | None = Field(default=None, alias="publishedAt")


class BunzyPost(BaseModel):
    """A full article from ``GET /posts/{slug}``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    slug: str
    title: str
    excerpt: str = ""
    markdown: str = ""
    language: str = "ru"
    tags: list[str] = Field(default_factory=list)
    key_takeaways: list[str] = Field(default_factory=list, alias="keyTakeaways")
    faq: list[BunzyFaq] = Field(default_factory=list)
    labels: BunzyLabels = Field(default_factory=BunzyLabels)
    seo: BunzySeo = Field(default_factory=BunzySeo)
    author: BunzyAuthor = Field(default_factory=BunzyAuthor)
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")
    reading_minutes: int | None = Field(default=None, alias="readingMinutes")
    published_at: str | None = Field(default=None, alias="publishedAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")


def is_configured() -> bool:
    """Whether a key is set. Without one the importer is a no-op, not an error."""
    return bool(get_settings().bunzy_api_key.strip())


class BunzyClient:
    """Thin wrapper over two GETs. Construct per pass, close when done."""

    def __init__(self, *, base_url: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        origin = (base_url or settings.bunzy_api_url).rstrip("/")
        self._key = api_key if api_key is not None else settings.bunzy_api_key
        self._client = httpx.AsyncClient(
            base_url=f"{origin}/api/v1",
            timeout=_TIMEOUT,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> BunzyClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._client.aclose()

    async def list_posts(self, *, limit: int = 20, page: int = 1) -> list[BunzySummary]:
        """Newest published articles first. Bunzy serves no drafts of its own."""
        payload = await self._get("/posts", params={"limit": limit, "page": page})
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise BunzyUnavailableError(200, "/posts")
        return [BunzySummary.model_validate(row) for row in rows]

    async def get_post(self, slug: str) -> BunzyPost:
        """One article with its markdown, FAQ and SEO block."""
        payload = await self._get(f"/posts/{slug}")
        body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        post = BunzyPost.model_validate(body)
        if len(post.markdown) > _MAX_MARKDOWN_CHARS:
            # The body column caps at 100k characters of *HTML*, which markup
            # inflates past the source. Refusing here names the article;
            # refusing in ``sanitize_body`` would only name a length.
            raise ValueError(f"bunzy article {slug!r} is {len(post.markdown)} characters")
        return post

    async def _get(self, path: str, *, params: dict[str, int] | None = None) -> dict[str, Any]:
        response = await self._client.get(
            path,
            params=params,
            headers={"Authorization": f"Bearer {self._key}"},
        )
        if response.status_code != httpx.codes.OK:
            # Status only: the body of a 4xx from an API we authenticate to
            # can echo the request, and the request carries the key.
            raise BunzyUnavailableError(response.status_code, path)
        payload = response.json()
        if not isinstance(payload, dict):
            raise BunzyUnavailableError(200, path)
        return payload


__all__ = [
    "BunzyClient",
    "BunzyFaq",
    "BunzyPost",
    "BunzySummary",
    "BunzyUnavailableError",
    "is_configured",
]
