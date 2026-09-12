"""Fail-closed HTML allowlist for editorial blog bodies.

Pure: no DB, no settings import. The caller passes the public media origin
so an off-host ``<img>`` cannot persist. Unknown tags, a second ``<h1>``,
comments and event-handler attributes raise ``ValidationError`` — they are
not stripped silently, because a future renderer will feed this string to
the storefront as HTML.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from yupay.core.errors import ValidationError

ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p",
        "h2",
        "h3",
        "ul",
        "ol",
        "li",
        "a",
        "img",
        "blockquote",
        "strong",
        "em",
        "code",
        "pre",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "hr",
        "br",
    }
)
VOID_TAGS: frozenset[str] = frozenset({"br", "hr", "img"})
_ANCHOR_SCHEMES: frozenset[str] = frozenset({"http", "https"})
_BODY_MAX_CHARS = 100_000
# TipTap's table pack always writes style/colspan/colwidth. Those are not
# XSS, but they trip the fail-closed attr rule. Strip them (and the
# ``colgroup`` it wraps around a resizable table) so a round-trip save works.
_TABLE_OPEN = re.compile(
    r"<(table|thead|tbody|tr|th|td)(?:\s[^>]*)?(/?)>",
    re.IGNORECASE,
)
_COLGROUP = re.compile(r"</?colgroup\b[^>]*>|<col\b[^>]*/?>", re.IGNORECASE)


def _normalize_tiptap_tables(html: str) -> str:
    """Drop TipTap table chrome; keep the tags the allowlist already names."""
    without_cols = _COLGROUP.sub("", html)
    return _TABLE_OPEN.sub(
        lambda match: f"<{match.group(1).lower()}{match.group(2)}>", without_cols
    )


class _ArticleHtmlValidator(HTMLParser):
    """Reject anything outside spec §8.1. Does not rewrite the input."""

    def __init__(self, *, media_base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self._media = urlsplit(media_base_url.rstrip("/"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "h1":
            raise ValidationError("h1 is the title field; the body must not contain <h1>")
        if tag not in ALLOWED_TAGS:
            raise ValidationError(f"disallowed tag: <{tag}>")
        names = [name for name, _value in attrs]
        if any(name.startswith("on") for name in names):
            raise ValidationError(f"<{tag}> must not have event-handler attributes")
        if tag == "a":
            self._check_anchor(attrs)
        elif tag == "img":
            self._check_img(attrs)
        elif attrs:
            raise ValidationError(f"<{tag}> must not have attributes")
        if tag not in VOID_TAGS:
            self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS:
            return
        if not self._stack or self._stack[-1] != tag:
            raise ValidationError(f"unbalanced or mis-nested tag: </{tag}>")
        self._stack.pop()

    def handle_comment(self, data: str) -> None:  # noqa: ARG002
        raise ValidationError("HTML comments are not allowed in a blog body")

    def handle_pi(self, data: str) -> None:  # noqa: ARG002
        raise ValidationError("processing instructions are not allowed in a blog body")

    def handle_decl(self, decl: str) -> None:  # noqa: ARG002
        raise ValidationError("HTML declarations are not allowed in a blog body")

    def unknown_decl(self, data: str) -> None:  # noqa: ARG002
        raise ValidationError("unknown declarations are not allowed in a blog body")

    def finish(self) -> None:
        if "<" in self.rawdata:
            raise ValidationError("incomplete or unterminated markup at end of body")
        self.close()
        if self._stack:
            raise ValidationError(f"unclosed tag: <{self._stack[-1]}>")

    def _check_anchor(self, attrs: list[tuple[str, str | None]]) -> None:
        names = [name for name, _value in attrs]
        if names != ["href"]:
            raise ValidationError("<a> must have exactly one 'href' attribute")
        href = attrs[0][1] or ""
        if href.startswith("/") and not href.startswith("//"):
            return
        try:
            parsed = urlsplit(href)
        except ValueError as exc:
            raise ValidationError(f"malformed href: {href!r}") from exc
        if parsed.scheme.lower() not in _ANCHOR_SCHEMES or not parsed.netloc:
            raise ValidationError(f"disallowed href scheme: {href!r}")

    def _check_img(self, attrs: list[tuple[str, str | None]]) -> None:
        got = {name: (value or "") for name, value in attrs}
        if set(got) != {"src", "alt"}:
            raise ValidationError("<img> must have exactly 'src' and 'alt'")
        if not got["alt"].strip():
            raise ValidationError("<img> alt is required")
        if len(got["alt"]) > 200:
            raise ValidationError("<img> alt is too long")
        assert_hosted_media(
            got["src"],
            media_base_url=self._media.geturl(),
            subject="img src",
        )


def sanitize_body(html: str, *, media_base_url: str, allow_empty: bool = True) -> str:
    """Validate ``html`` and return the persistable form.

    Table tags are rewritten first: TipTap always serializes ``style`` /
    ``colspan`` / ``colgroup``, which the allowlist does not keep. Every
    other tag is still fail-closed — extra attributes raise, they are not
    stripped.

    Args:
        html: admin-authored article HTML.
        media_base_url: public CDN origin (no trailing slash), e.g.
            ``https://cdn.yupay.uz``.
        allow_empty: drafts may have no body; publish must pass ``False``.

    Raises:
        ValidationError: disallowed markup, empty body when not allowed, or
            a body over :data:`_BODY_MAX_CHARS`.
    """
    if len(html) > _BODY_MAX_CHARS:
        raise ValidationError(f"body is {len(html)} characters, over {_BODY_MAX_CHARS}")
    stripped = html.strip()
    if not stripped:
        if allow_empty:
            return ""
        raise ValidationError("body is empty")
    if "<!" in html or "<?" in html:
        raise ValidationError(
            "HTML comments, declarations, and processing instructions are not allowed"
        )
    normalized = _normalize_tiptap_tables(html)
    validator = _ArticleHtmlValidator(media_base_url=media_base_url)
    validator.feed(normalized)
    validator.finish()
    return normalized


def assert_hosted_media(url: str, *, media_base_url: str, subject: str = "url") -> str:
    """Reject ``url`` unless it is served from ``media_base_url``.

    Args:
        url: candidate absolute URL.
        media_base_url: public CDN origin (trailing slash ignored).
        subject: noun for the error message (``cover``, ``img src``).

    Returns:
        ``url`` unchanged.

    Raises:
        ValidationError: scheme/host do not match the configured media origin.
    """
    media = urlsplit(media_base_url.rstrip("/"))
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValidationError(f"malformed {subject}: {url!r}") from exc
    if (
        parsed.scheme != media.scheme
        or parsed.netloc != media.netloc
        or not parsed.path.startswith("/")
    ):
        raise ValidationError(f"{subject} must be served from the configured media host")
    return url


__all__ = ["ALLOWED_TAGS", "assert_hosted_media", "sanitize_body"]
