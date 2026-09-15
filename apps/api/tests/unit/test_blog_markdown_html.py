"""Markdown → the blog allowlist. Every construct, and what happens to it.

The point of these is not that the converter runs — it is that the formatting
survives. An imported article that lost its headings, its links or its lists
would still save, still publish and still look wrong, so each construct is
asserted on its own and the whole result is put back through
``sanitize_body``: whatever this module emits, the fail-closed validator has
to accept unchanged, or the import would fail at the last step.
"""

from __future__ import annotations

import pytest
from yupay.core.errors import ValidationError
from yupay.modules.blog.markdown_html import markdown_to_html
from yupay.modules.blog.sanitize import sanitize_body

_CDN = "https://cdn.yupay.uz"


def _html(markdown: str) -> str:
    return markdown_to_html(markdown).html


def test_paragraphs_stay_paragraphs() -> None:
    assert _html("Первый абзац.\n\nВторой абзац.") == ("<p>Первый абзац.</p>\n<p>Второй абзац.</p>")


def test_h2_survives_and_deeper_headings_are_demoted() -> None:
    result = markdown_to_html("## Как пополнить\n\n### Шаги\n\n#### Мелочи")
    assert "<h2>Как пополнить</h2>" in result.html
    assert "<h3>Шаги</h3>" in result.html
    # h4 has no home in the allowlist; losing the heading would lose the
    # outline, so it becomes the deepest one we do render.
    assert "<h3>Мелочи</h3>" in result.html
    assert result.demoted_headings == 1


def test_h1_becomes_h2_because_the_body_may_not_carry_one() -> None:
    assert _html("# Заголовок статьи") == "<h2>Заголовок статьи</h2>"


def test_heading_anchor_extension_is_not_rendered_as_text() -> None:
    assert _html("## Сроки {#terms}") == "<h2>Сроки</h2>"


def test_links_keep_their_href_and_lose_their_title() -> None:
    html = _html('Смотри [Kun.uz](https://kun.uz/news "источник") про переводы.')
    assert html == '<p>Смотри <a href="https://kun.uz/news">Kun.uz</a> про переводы.</p>'


def test_site_relative_links_are_kept() -> None:
    assert _html("[Купить](/store/steam)") == '<p><a href="/store/steam">Купить</a></p>'


def test_link_with_an_unusable_scheme_keeps_its_text() -> None:
    # Dropping the article over one `mailto:` would be the wrong trade: the
    # words are the content, the anchor is decoration.
    result = markdown_to_html("Пишите [нам](mailto:hi@yupay.uz).")
    assert result.html == "<p>Пишите нам.</p>"
    assert result.unwrapped_links == 1


def test_bold_italic_and_code_are_kept() -> None:
    assert _html("**жирный**, *курсив*, `код`") == (
        "<p><strong>жирный</strong>, <em>курсив</em>, <code>код</code></p>"
    )


def test_both_list_kinds_are_kept() -> None:
    assert _html("- раз\n- два") == "<ul>\n<li>раз</li>\n<li>два</li>\n</ul>"
    assert _html("1. раз\n2. два") == "<ol>\n<li>раз</li>\n<li>два</li>\n</ol>"


def test_nested_lists_keep_their_nesting() -> None:
    html = _html("- раз\n  - вложенный")
    assert html.count("<ul>") == 2
    assert "<li>вложенный</li>" in html


def test_blockquote_and_rule_are_kept() -> None:
    assert _html("> цитата") == "<blockquote>\n<p>цитата</p>\n</blockquote>"
    assert _html("текст\n\n---\n\nещё") == "<p>текст</p>\n<hr>\n<p>ещё</p>"


def test_fenced_code_loses_only_its_language_class() -> None:
    html = _html('```python\nprint("x")\n```')
    assert html == '<pre><code>print("x")\n</code></pre>'.replace('"', "&quot;")


def test_tables_keep_their_cells_and_lose_the_alignment_style() -> None:
    html = _html("| Способ | Срок |\n|---|--:|\n| Uzcard | 1 мин |")
    assert "<th>Способ</th>" in html
    assert "<td>1 мин</td>" in html
    assert "style" not in html


def test_strikethrough_keeps_the_words() -> None:
    assert _html("было ~~дорого~~ дёшево") == "<p>было дорого дёшево</p>"


def test_hard_break_becomes_br() -> None:
    assert _html("строка один  \nстрока два") == "<p>строка один<br>\nстрока два</p>"


def test_images_are_dropped_with_the_paragraph_that_held_them() -> None:
    # Every picture a third party sends lives on their CDN, and the allowlist
    # refuses media off our own origin. An editor uploads it by hand.
    result = markdown_to_html(
        "До.\n\n![Игровая станция](https://cdn.bunzy.io/media/inline/x.jpg)\n\nПосле."
    )
    assert result.html == "<p>До.</p>\n<p>После.</p>"
    assert result.dropped_images == 1


def test_an_inline_image_leaves_the_sentence_readable() -> None:
    assert _html("Текст ![p](https://c.io/x.jpg) дальше.") == "<p>Текст дальше.</p>"


def test_raw_html_in_the_source_becomes_text() -> None:
    html = _html("<script>alert(1)</script> и <span>span</span>")
    assert "<script" not in html
    assert "&lt;script&gt;" in html


@pytest.mark.parametrize(
    "markdown",
    [
        "# h1\n\n## h2\n\n### h3\n\n#### h4",
        "- раз\n- два\n\n1. три\n\n> цитата\n\n---",
        "[внешняя](https://kun.uz) и [своя](/store) и ![чужая](https://cdn.bunzy.io/x.jpg)",
        "| a | b |\n|--:|:-:|\n| 1 | 2 |",
        "```sh\nls -la && echo '<b>'\n```",
        "**жирный** *курсив* `код` ~~зачёркнутый~~",
    ],
)
def test_output_is_accepted_by_the_fail_closed_sanitizer(markdown: str) -> None:
    html = markdown_to_html(markdown).html
    assert sanitize_body(html, media_base_url=_CDN, allow_empty=False) == html


def test_an_empty_source_is_empty_not_an_error() -> None:
    assert markdown_to_html("   \n\n  ").html == ""


def test_a_body_of_nothing_but_an_image_does_not_produce_stray_markup() -> None:
    html = markdown_to_html("![x](https://cdn.bunzy.io/x.jpg)").html
    assert html == ""
    with pytest.raises(ValidationError, match="empty"):
        sanitize_body(html, media_base_url=_CDN, allow_empty=False)
