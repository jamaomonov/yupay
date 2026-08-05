"""Review body / author-name HTML stripping (defense-in-depth stored-XSS guard).

Review bodies and Telegram-sourced author names are served on the public
``GET /reviews/brands/{slug}``. The web renders them as React text (escaped),
but we strip HTML server-side too so a future ``dangerouslySetInnerHTML`` on
this data can't turn stored attacker markup into script execution.
"""

from __future__ import annotations

from yupay.modules.reviews.service import _strip_html


def test_strips_script_and_tags_keeping_text() -> None:
    assert _strip_html("<script>alert(1)</script>hello") == "alert(1)hello"
    assert _strip_html("<b>bold</b> and <i>italic</i>") == "bold and italic"
    assert _strip_html('<img src=x onerror="alert(1)">') == ""


def test_keeps_plain_text_and_bare_comparisons() -> None:
    assert _strip_html("great deal, 5 < 10 stars!") == "great deal, 5 < 10 stars!"
    assert _strip_html("no markup here") == "no markup here"


def test_handles_none_and_empty() -> None:
    assert _strip_html(None) is None
    assert _strip_html("") == ""
