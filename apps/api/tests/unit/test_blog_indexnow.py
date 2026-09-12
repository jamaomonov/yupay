"""Unit tests for blog IndexNow URL shaping and the IndexNow POST."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
import respx
from yupay.modules.blog.indexnow import (
    INDEXNOW_ENDPOINT,
    INDEXNOW_KEY,
    IndexNowRejectedError,
    locale_prefix,
    post_indexnow,
    public_urls,
)


def test_locale_prefix_omits_ru() -> None:
    assert locale_prefix("ru") == ""
    assert locale_prefix("en") == "/en"
    assert locale_prefix("uz") == "/uz"


def test_public_urls_are_production_and_include_the_index() -> None:
    post = SimpleNamespace(
        translations=[
            SimpleNamespace(locale="ru", slug="kak-popolnit"),
            SimpleNamespace(locale="en", slug="how-to-top-up"),
        ]
    )
    assert public_urls(post) == [  # type: ignore[arg-type]
        "https://yupay.uz/blog/kak-popolnit",
        "https://yupay.uz/blog",
        "https://yupay.uz/en/blog/how-to-top-up",
        "https://yupay.uz/en/blog",
    ]


@pytest.mark.asyncio
@respx.mock
async def test_post_indexnow_accepts_202() -> None:
    route = respx.post(INDEXNOW_ENDPOINT).mock(return_value=httpx.Response(202))
    await post_indexnow(["https://yupay.uz/blog/kak-popolnit"])
    assert route.called
    sent = route.calls[0].request
    assert sent.headers["content-type"].startswith("application/json")
    body = sent.content.decode()
    assert INDEXNOW_KEY in body
    assert "https://yupay.uz/blog/kak-popolnit" in body


@pytest.mark.asyncio
@respx.mock
async def test_post_indexnow_rejects_4xx() -> None:
    respx.post(INDEXNOW_ENDPOINT).mock(return_value=httpx.Response(422))
    with pytest.raises(IndexNowRejectedError) as err:
        await post_indexnow(["https://yupay.uz/blog/x"])
    assert err.value.status_code == 422
