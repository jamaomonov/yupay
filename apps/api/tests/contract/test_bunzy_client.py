"""Recorded shape of the Bunzy blog API.

Two things are worth pinning: that the camelCase payload maps onto our
snake_case fields (a silent rename upstream would otherwise arrive as an
article with no FAQ and no SEO), and that a failure carries the status and
nothing else — the key travels in the request, and a 4xx body from an API
you authenticate to can echo the request back at you.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.modules.blog.bunzy_client import BunzyClient, BunzyUnavailableError

pytestmark = pytest.mark.contract

_BASE = "https://app.bunzy.io/api/v1"
_KEY = "sk_test_key"

_POST = {
    "slug": "steam",
    "title": "Как пополнить Steam в Узбекистане",
    "excerpt": "Картами Uzcard и Humo.",
    "markdown": "## Шаги\n\n1. Откройте сайт.\n",
    "language": "ru",
    "tags": ["steam"],
    "readingMinutes": 5,
    "keyTakeaways": ["Платите в сумах."],
    "labels": {"keyTakeaways": "Главное", "faq": "Часто задаваемые вопросы"},
    "faq": [{"question": "Комиссия есть?", "answer": "Нет."}],
    "seo": {
        "metaTitle": "Пополнить Steam",
        "metaDescription": "Инструкция.",
        "canonicalUrl": "https://yupay.uz/blog/steam",
        "ogImage": "https://cdn.bunzy.io/media/thumbnails/x.webp",
        "focusKeyword": "пополнить steam",
        "jsonLd": {"@context": "https://schema.org", "@graph": []},
    },
    "author": {"name": "Jam Omonov"},
    "thumbnailUrl": "https://cdn.bunzy.io/media/thumbnails/x.webp",
    "publishedAt": "2026-09-15T11:01:39.515Z",
    "updatedAt": "2026-09-15T11:01:39.521Z",
}


def _client() -> BunzyClient:
    return BunzyClient(base_url="https://app.bunzy.io", api_key=_KEY)


@respx.mock
async def test_the_feed_lists_slugs_and_revisions() -> None:
    route = respx.get(f"{_BASE}/posts").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"slug": "steam", "title": "…", "updatedAt": "2026-09-15T11:01:39.521Z"}],
                "pagination": {"page": 1, "limit": 20, "total": 1, "totalPages": 1},
            },
        )
    )
    async with _client() as client:
        rows = await client.list_posts(limit=20)

    assert [row.slug for row in rows] == ["steam"]
    assert rows[0].updated_at == "2026-09-15T11:01:39.521Z"
    assert route.calls.last.request.headers["authorization"] == f"Bearer {_KEY}"


@respx.mock
async def test_an_article_maps_onto_our_fields() -> None:
    respx.get(f"{_BASE}/posts/steam").mock(return_value=httpx.Response(200, json=_POST))
    async with _client() as client:
        post = await client.get_post("steam")

    assert post.language == "ru"
    assert post.key_takeaways == ["Платите в сумах."]
    assert post.labels.key_takeaways == "Главное"
    assert [row.question for row in post.faq] == ["Комиссия есть?"]
    assert post.seo.meta_title == "Пополнить Steam"
    assert post.seo.meta_description == "Инструкция."
    assert post.thumbnail_url == "https://cdn.bunzy.io/media/thumbnails/x.webp"
    assert post.updated_at == "2026-09-15T11:01:39.521Z"


@respx.mock
async def test_an_unknown_field_upstream_does_not_break_the_import() -> None:
    respx.get(f"{_BASE}/posts/steam").mock(
        return_value=httpx.Response(200, json={**_POST, "newThing": {"a": 1}})
    )
    async with _client() as client:
        assert (await client.get_post("steam")).slug == "steam"


@respx.mock
async def test_a_rejected_key_raises_with_the_status_and_no_body() -> None:
    respx.get(f"{_BASE}/posts").mock(
        return_value=httpx.Response(401, json={"error": f"bad key {_KEY}"})
    )
    async with _client() as client:
        with pytest.raises(BunzyUnavailableError) as caught:
            await client.list_posts()

    assert caught.value.status_code == 401
    assert _KEY not in str(caught.value)


@respx.mock
async def test_an_article_too_long_for_the_body_column_is_refused_by_name() -> None:
    respx.get(f"{_BASE}/posts/steam").mock(
        return_value=httpx.Response(200, json={**_POST, "markdown": "x" * 90_000})
    )
    async with _client() as client:
        with pytest.raises(ValueError, match="steam"):
            await client.get_post("steam")
