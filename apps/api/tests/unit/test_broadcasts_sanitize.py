"""Telegram-HTML validator (``sanitize.py``) — the save-time chokepoint.

An admin-authored broadcast body must be safe to hand to Telegram's HTML parse
mode before it is ever persisted, so a malformed body never reaches the
fan-out job. ``validate_body`` is a strict whitelist: only the tags Telegram's
Bot API documents are allowed, ``a`` may only carry a scheme-checked ``href``,
every other allowed tag must carry no attributes at all, and tags must nest
and close correctly. ``visible_length`` undercounts markup so the caption
(1024 chars with media) and message (4096 chars without) limits are enforced
against what the recipient actually sees, not the raw markup.
"""

from __future__ import annotations

import pytest
from yupay.core.errors import ValidationError
from yupay.modules.broadcasts.sanitize import ALLOWED_TAGS, validate_body, visible_length


def test_allowed_tags_frozenset_matches_telegram_html_whitelist() -> None:
    assert frozenset(
        {"b", "i", "u", "s", "a", "code", "pre", "tg-spoiler", "blockquote"}
    ) == ALLOWED_TAGS


def test_plain_text_passes() -> None:
    validate_body("just plain text, no markup at all", has_media=False)


@pytest.mark.parametrize(
    "html",
    [
        "<b>x</b>",
        "<i>x</i>",
        "<u>x</u>",
        "<s>x</s>",
        "<code>x</code>",
        "<pre>x</pre>",
        "<tg-spoiler>x</tg-spoiler>",
        "<blockquote>x</blockquote>",
        '<a href="https://a.b">x</a>',
    ],
)
def test_each_allowed_tag_passes(html: str) -> None:
    validate_body(html, has_media=False)


@pytest.mark.parametrize(
    "scheme_href",
    ["http://a.b", "https://a.b", "tg://user?id=1"],
)
def test_anchor_allowed_schemes_pass(scheme_href: str) -> None:
    validate_body(f'<a href="{scheme_href}">x</a>', has_media=False)


def test_script_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body("<script>alert(1)</script>", has_media=False)


def test_div_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body("<div>x</div>", has_media=False)


def test_stray_attr_on_non_anchor_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body('<b class="x">x</b>', has_media=False)


def test_anchor_with_bad_scheme_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body('<a href="javascript:alert(1)">x</a>', has_media=False)


def test_anchor_missing_href_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body("<a>x</a>", has_media=False)


def test_anchor_with_extra_attr_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body('<a href="https://a.b" onclick="x">x</a>', has_media=False)


def test_mis_nested_tags_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body("<b><i>x</b></i>", has_media=False)


def test_unbalanced_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body("<b>x", has_media=False)


def test_over_length_caption_with_media_rejected() -> None:
    body = "a" * 1025
    with pytest.raises(ValidationError):
        validate_body(body, has_media=True)


def test_2000_visible_chars_without_media_passes() -> None:
    body = "a" * 2000
    validate_body(body, has_media=False)


def test_4097_visible_chars_without_media_rejected() -> None:
    body = "a" * 4097
    with pytest.raises(ValidationError):
        validate_body(body, has_media=False)


def test_visible_length_strips_tags_and_decodes_entities() -> None:
    assert visible_length("<b>ab</b>&amp;c") == 4
