"""Blog body HTML: fail-closed allowlist (spec §8.1)."""

from __future__ import annotations

import pytest
from yupay.core.errors import ValidationError
from yupay.modules.blog.sanitize import _ArticleHtmlValidator, assert_hosted_media, sanitize_body

_CDN = "https://cdn.yupay.uz"


def test_keeps_an_article_shaped_body() -> None:
    html = (
        "<h2>Как пополнить</h2><p>Нужен <strong>player id</strong>.</p>"
        "<ol><li>Откройте игру</li></ol>"
        f'<p><img src="{_CDN}/blog/2026/09/x.webp" alt="экран ID"></p>'
        '<p><a href="/store/mobile-legends">Купить UC</a></p>'
    )
    assert sanitize_body(html, media_base_url=_CDN) == html


def test_rejects_h1() -> None:
    with pytest.raises(ValidationError, match="h1"):
        sanitize_body("<h1>второй заголовок</h1><p>текст</p>", media_base_url=_CDN)


def test_rejects_script() -> None:
    with pytest.raises(ValidationError, match="script"):
        sanitize_body("<p>ok</p><script>alert(1)</script>", media_base_url=_CDN)


def test_rejects_off_host_image() -> None:
    with pytest.raises(ValidationError, match="img"):
        sanitize_body('<img src="https://evil.test/x.png" alt="x">', media_base_url=_CDN)


def test_rejects_image_without_alt() -> None:
    with pytest.raises(ValidationError, match="alt"):
        sanitize_body(f'<img src="{_CDN}/blog/x.webp">', media_base_url=_CDN)


def test_rejects_javascript_href() -> None:
    with pytest.raises(ValidationError, match="href"):
        sanitize_body('<a href="javascript:alert(1)">x</a>', media_base_url=_CDN)


def test_rejects_protocol_relative_href() -> None:
    with pytest.raises(ValidationError, match="href"):
        sanitize_body('<a href="//evil.test/phish">x</a>', media_base_url=_CDN)


def test_empty_body_is_allowed_for_drafts() -> None:
    assert sanitize_body("", media_base_url=_CDN, allow_empty=True) == ""
    with pytest.raises(ValidationError, match="empty"):
        sanitize_body("   ", media_base_url=_CDN, allow_empty=False)


def test_rejects_html_comment() -> None:
    with pytest.raises(ValidationError, match=r"comment|declaration"):
        sanitize_body("<p>ok</p><!-- x -->", media_base_url=_CDN)


def test_rejects_unclosed_tag() -> None:
    with pytest.raises(ValidationError, match="unclosed"):
        sanitize_body("<p>ok", media_base_url=_CDN)


def test_rejects_event_handler() -> None:
    with pytest.raises(ValidationError, match="event-handler"):
        sanitize_body('<p onclick="x">x</p>', media_base_url=_CDN)


def test_rejects_attribute_on_paragraph() -> None:
    with pytest.raises(ValidationError, match="attributes"):
        sanitize_body('<p class="lead">x</p>', media_base_url=_CDN)


def test_rejects_unbalanced_end_tag() -> None:
    with pytest.raises(ValidationError, match="unbalanced"):
        sanitize_body("</p>", media_base_url=_CDN)


def test_rejects_anchor_with_extra_attr() -> None:
    with pytest.raises(ValidationError, match="href"):
        sanitize_body('<a href="/x" target="_blank">x</a>', media_base_url=_CDN)


def test_rejects_blank_alt() -> None:
    with pytest.raises(ValidationError, match="alt"):
        sanitize_body(f'<img src="{_CDN}/blog/x.webp" alt="  ">', media_base_url=_CDN)


def test_rejects_oversized_alt() -> None:
    with pytest.raises(ValidationError, match="alt"):
        sanitize_body(f'<img src="{_CDN}/blog/x.webp" alt="{"a" * 201}">', media_base_url=_CDN)


def test_rejects_oversized_body() -> None:
    with pytest.raises(ValidationError, match="over"):
        sanitize_body("<p>" + ("a" * 100_000) + "</p>", media_base_url=_CDN)


def test_keeps_https_href_and_void_br() -> None:
    html = '<p>ok<br><a href="https://yupay.uz/store">x</a></p>'
    assert sanitize_body(html, media_base_url=_CDN) == html


def test_rejects_unterminated_tag() -> None:
    with pytest.raises(ValidationError, match="unterminated"):
        sanitize_body('<p class="', media_base_url=_CDN)


def test_assert_hosted_media_rejects_off_host() -> None:
    with pytest.raises(ValidationError, match="media host"):
        assert_hosted_media("https://evil.test/x.png", media_base_url=_CDN)


def test_defensive_parser_callbacks_reject() -> None:
    validator = _ArticleHtmlValidator(media_base_url=_CDN)
    with pytest.raises(ValidationError, match="comment"):
        validator.handle_comment("x")
    with pytest.raises(ValidationError, match="processing"):
        validator.handle_pi("x")
    with pytest.raises(ValidationError, match="declaration"):
        validator.handle_decl("DOCTYPE html")
    with pytest.raises(ValidationError, match="declaration"):
        validator.unknown_decl("ENTITY x")
    validator.handle_endtag("img")
