"""Markdown → the blog body allowlist, for copy imported from a third party.

Our own editor writes HTML through TipTap and :mod:`sanitize` guards it.
Imported copy arrives as Markdown instead, so it needs a *converter* whose
output already sits inside that allowlist. A converter that emitted ``<h1>``
or a ``class=`` and left ``sanitize_body`` to reject it would turn one stray
heading into a lost article — and the point of the import is that nothing in
the formatting is lost.

Parsing is markdown-it-py (CommonMark + GFM tables, ADR-0077). Everything
project-specific happens on the **token stream**, before rendering: a tag the
allowlist does not name is retagged or dropped there, never patched out of
finished HTML with a regex. ``sanitize_body`` still runs over the result —
this module is the mapping, not the guard.

The mapping, construct by construct:

- ``#`` … ``######`` → ``h2`` for levels 1–2, ``h3`` for 3–6. The body must
  not carry an ``h1`` (that is the title field), and the allowlist stops at
  ``h3``; demoting keeps the outline rather than dropping the heading.
- A trailing ``{#anchor}`` on a heading is removed. It is an extension our
  renderer does not implement, so it would otherwise show as literal text.
- ``[text](url)`` → ``<a href>``, with the ``title=`` dropped. An ``href``
  that is neither ``http(s)`` nor site-root-relative loses its tag and keeps
  its text — an import must not fail over one ``mailto:``.
- ``![alt](url)`` → dropped, with the paragraph that held it. Every image a
  third party sends us lives on *their* CDN, and ``assert_hosted_media``
  refuses anything off our own media origin; an editor uploads the picture.
- ``~~text~~`` → the text, unwrapped. ``<s>``/``<del>`` is not on the
  allowlist.
- Fenced code keeps ``<pre><code>`` and loses the ``language-*`` class.
- GFM tables keep their tags and lose the ``style="text-align:…"``.
- Raw HTML in the source is escaped to text: the parser runs with
  ``html=False``, so a ``<script>`` in the feed becomes visible characters
  and never a tag.
"""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.token import Token
from pydantic import BaseModel, ConfigDict

# ``## Heading {#slug}`` — an anchor extension we do not render.
_ANCHOR_SUFFIX = re.compile(r"\s*\{#[\w-]+\}\s*$")
# Schemes an <a href> may keep. Anything else is unwrapped, not an error.
_ANCHOR_SCHEMES = ("http://", "https://")
_UNWRAPPED = frozenset({"s_open", "s_close"})


class ConversionResult(BaseModel):
    """Converted body plus what the mapping had to give up, for the log."""

    model_config = ConfigDict(frozen=True)

    html: str
    dropped_images: int = 0
    unwrapped_links: int = 0
    demoted_headings: int = 0


def markdown_to_html(markdown: str) -> ConversionResult:
    """Render ``markdown`` as HTML that ``sanitize_body`` accepts.

    Args:
        markdown: GFM source from the upstream feed.

    Returns:
        The HTML and a count of each construct the allowlist could not keep.
    """
    parser = _parser()
    tokens = parser.parse(markdown)
    counters = _Counters()
    kept = _rewrite(tokens, counters)
    html = parser.renderer.render(kept, parser.options, {})
    return ConversionResult(
        html=html.strip(),
        dropped_images=counters.images,
        unwrapped_links=counters.links,
        demoted_headings=counters.headings,
    )


class _Counters:
    """Mutable tally threaded through the rewrite; reported, never raised on."""

    def __init__(self) -> None:
        self.images = 0
        self.links = 0
        self.headings = 0


def _parser() -> MarkdownIt:
    """A fresh parser per call — ``MarkdownIt`` carries per-parse state."""
    # "default" is CommonMark plus GFM tables and strikethrough, with
    # ``html`` off and ``linkify`` off. Both defaults matter: raw HTML from a
    # feed we do not control must stay text, and auto-linking bare URLs would
    # invent anchors the author did not write.
    return MarkdownIt("default")


def _rewrite(tokens: list[Token], counters: _Counters) -> list[Token]:
    """Retag, unwrap and drop until only allowlisted tags remain.

    Two passes on purpose: a paragraph is only known to be empty *after* its
    inline token has lost the image it held, and the emptiness test reads the
    token that follows the one being visited.
    """
    for token in tokens:
        if token.type == "inline":
            _rewrite_inline(token, counters)
        elif token.type in {"heading_open", "heading_close"}:
            _demote(token, counters)
        elif token.type in {"th_open", "td_open"}:
            token.attrs = {}
        elif token.type == "fence":
            token.info = ""
    out: list[Token] = []
    index = 0
    while index < len(tokens):
        if _is_empty_paragraph(tokens, index):
            index += 3
            continue
        out.append(tokens[index])
        index += 1
    return out


def _rewrite_inline(token: Token, counters: _Counters) -> None:
    """Filter one inline token's children in place."""
    children = token.children or []
    kept: list[Token] = []
    dropping_link = False
    removed = False
    for child in children:
        if child.type == "image":
            counters.images += 1
            removed = True
            continue
        if child.type in _UNWRAPPED:
            continue
        if child.type == "link_open":
            href = str(child.attrs.get("href", ""))
            if not _href_allowed(href):
                counters.links += 1
                dropping_link = True
                continue
            # ``title=`` is the only other attribute markdown-it emits here,
            # and the allowlist permits exactly one attribute on <a>.
            child.attrs = {"href": href}
        elif child.type == "link_close" and dropping_link:
            dropping_link = False
            continue
        if removed and _join_text(kept, child):
            removed = False
            continue
        removed = False
        kept.append(child)
    token.children = kept
    _strip_anchor(kept)


def _join_text(kept: list[Token], child: Token) -> bool:
    """Close the gap a dropped child left between two runs of text.

    "Text then ![pic](…) then more." would otherwise render with the two
    spaces that hugged the image. Returns ``True`` when ``child`` was merged
    into the previous token and must not be appended again.
    """
    if child.type != "text" or not kept or kept[-1].type != "text":
        return False
    left, right = kept[-1].content, child.content
    if not left.endswith(" ") or not right.startswith(" "):
        return False
    kept[-1].content = left + right.lstrip(" ")
    return True


def _href_allowed(href: str) -> bool:
    """``http(s)`` absolute, or site-root-relative. ``//host`` is neither."""
    if href.startswith("/"):
        return not href.startswith("//")
    return href.lower().startswith(_ANCHOR_SCHEMES)


def _strip_anchor(children: list[Token]) -> None:
    """Remove a trailing ``{#slug}`` from the last text run of a heading."""
    if not children:
        return
    last = children[-1]
    if last.type != "text":
        return
    last.content = _ANCHOR_SUFFIX.sub("", last.content)


def _demote(token: Token, counters: _Counters) -> None:
    """``h1``/``h2`` → ``h2``; ``h3``…``h6`` → ``h3``."""
    target = "h2" if token.tag in {"h1", "h2"} else "h3"
    if token.tag != target and token.type == "heading_open":
        counters.headings += 1
    token.tag = target


def _is_empty_paragraph(tokens: list[Token], index: int) -> bool:
    """True for a ``<p>`` whose whole content was an image we just dropped."""
    if tokens[index].type != "paragraph_open" or index + 2 >= len(tokens):
        return False
    inline, close = tokens[index + 1], tokens[index + 2]
    if inline.type != "inline" or close.type != "paragraph_close":
        return False
    return not any(child.content.strip() for child in inline.children or [])


__all__ = ["ConversionResult", "markdown_to_html"]
