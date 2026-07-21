"""Telegram-HTML whitelist validator for admin-authored broadcast bodies.

Pure, I/O-free module: no DB, no network. This is the save-time chokepoint — a body that
passes :func:`validate_body` is guaranteed safe to send to Telegram's HTML parse mode, so a
malformed body never reaches the fan-out job. Built on the stdlib ``html.parser.HTMLParser``
(no new dependency); tag/attribute names it reports are already lower-cased, including the
custom tag name ``tg-spoiler``.
"""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit

from yupay.core.errors import ValidationError

ALLOWED_TAGS: frozenset[str] = frozenset(
    {"b", "i", "u", "s", "a", "code", "pre", "tg-spoiler", "blockquote"}
)

_ALLOWED_ANCHOR_SCHEMES: frozenset[str] = frozenset({"http", "https", "tg"})
_CAPTION_LIMIT = 1024
_MESSAGE_LIMIT = 4096


class _TextCollector(HTMLParser):
    """Accumulates raw text content, ignoring all tags — used by ``visible_length``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    @property
    def text(self) -> str:
        """The concatenated text seen so far."""
        return "".join(self._parts)


def visible_length(html: str) -> int:
    """Return the length of ``html`` as the recipient will actually see it.

    Strips every tag and decodes HTML entities (via :func:`html.unescape`) — this is the
    count Telegram's caption/message length limits are enforced against, not the length of
    the raw markup.
    """
    collector = _TextCollector()
    collector.feed(html)
    collector.close()
    return len(unescape(collector.text))


class _TelegramHtmlValidator(HTMLParser):
    """Validates a Telegram-HTML body against :data:`ALLOWED_TAGS`.

    Tracks an open-tag stack: every start tag must be allowed, ``a`` must carry exactly an
    ``href`` attribute whose scheme is in ``{http, https, tg}``, every other allowed tag must
    carry no attributes at all, and every end tag must close the innermost open tag — anything
    else raises :class:`ValidationError` immediately, from inside the parser callback.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in ALLOWED_TAGS:
            raise ValidationError(f"disallowed tag: <{tag}>")
        if tag == "a":
            names = [name for name, _value in attrs]
            if names != ["href"]:
                raise ValidationError("<a> must have exactly one 'href' attribute")
            href = attrs[0][1] or ""
            try:
                scheme = urlsplit(href).scheme.lower()
            except ValueError as exc:
                raise ValidationError(f"malformed href: {href!r}") from exc
            if scheme not in _ALLOWED_ANCHOR_SCHEMES:
                raise ValidationError(f"disallowed href scheme: {scheme!r}")
        elif attrs:
            raise ValidationError(f"<{tag}> must not have attributes")
        self._stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack or self._stack[-1] != tag:
            raise ValidationError(f"unbalanced or mis-nested tag: </{tag}>")
        self._stack.pop()

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def finish(self) -> str:
        """Close the parser and return the accumulated text.

        Raises:
            ValidationError: if any tag was left open (unbalanced markup).
        """
        self.close()
        if self._stack:
            raise ValidationError(f"unclosed tag: <{self._stack[-1]}>")
        return "".join(self._parts)


def validate_body(html: str, *, has_media: bool) -> None:
    """Validate an admin-authored Telegram-HTML broadcast body.

    Empty ``html`` is only meaningful together with an attached media item; enforcing that
    combination is the caller's job (see ``service.py``) — this function only checks the tag
    whitelist and the length ceiling.

    Args:
        html: the admin-authored body, in Telegram's HTML subset.
        has_media: whether the broadcast also attaches a media item, which caps the visible
            length at Telegram's caption limit (1024) instead of the message limit (4096).

    Raises:
        ValidationError: on a disallowed tag or attribute, a disallowed ``a`` href scheme,
            unbalanced or mis-nested tags, or a visible length over the applicable ceiling.
    """
    validator = _TelegramHtmlValidator()
    validator.feed(html)
    text = validator.finish()
    limit = _CAPTION_LIMIT if has_media else _MESSAGE_LIMIT
    length = len(unescape(text))
    if length > limit:
        kind = "caption" if has_media else "message"
        raise ValidationError(
            f"body is {length} visible characters, over the {kind} limit of {limit}"
        )


__all__ = ["ALLOWED_TAGS", "validate_body", "visible_length"]
