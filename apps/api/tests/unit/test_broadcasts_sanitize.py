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


def test_visible_length_decodes_entity_exactly_once() -> None:
    # "&amp;amp;" is the entity "&amp;" (-> "&") followed by literal text "amp;" — a single
    # decode pass, not two. Double-decoding this would collapse it to "&" (length 1) instead
    # of the true visible text "&amp;" (length 5), defeating the length ceiling below.
    assert visible_length("&amp;amp;") == 5


def test_nested_entity_body_over_ceiling_rejected() -> None:
    # 2000 repetitions of "&amp;amp;" is 18000 raw chars but only 10000 visible chars once
    # decoded a single time — still well over the 4096 ceiling, so this must be rejected.
    # (A double-decode bug would instead collapse it to 2000 visible chars and let it pass.)
    body = "&amp;amp;" * 2000
    with pytest.raises(ValidationError):
        validate_body(body, has_media=False)


def test_terminated_comment_hiding_script_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body("hello <!-- <script>alert(1)</script> --> world", has_media=False)


def test_unterminated_comment_rejected() -> None:
    # An unterminated comment swallows everything to EOF in a naive HTMLParser-based
    # validator (the disallowed <script> and <i> tags inside never reach
    # handle_starttag/handle_endtag at all) — must still be rejected.
    with pytest.raises(ValidationError):
        validate_body("a <!-- <script>x</script> <i> b", has_media=False)


def test_processing_instruction_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body("<?pi?>", has_media=False)


def test_declaration_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body("<!decl>", has_media=False)


def test_unterminated_attribute_quote_rejected() -> None:
    # An unclosed `class="` attribute-quote construct is buffered by HTMLParser as
    # incomplete and never reaches handle_starttag/handle_data at all — it must not be
    # able to swallow the rest of the body (here ~3500 hidden chars) uncounted.
    payload = 'short visible <b class="' + ("HIDDEN_" * 500) + " no closing quote or bracket"
    with pytest.raises(ValidationError):
        validate_body(payload, has_media=True)


def test_bare_unterminated_tag_at_eof_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body("<b", has_media=False)


def test_unterminated_anchor_href_no_closing_bracket_rejected() -> None:
    with pytest.raises(ValidationError):
        validate_body('<a href="x"', has_media=False)


def test_literal_greater_than_in_text_passes() -> None:
    validate_body("a > b", has_media=False)
