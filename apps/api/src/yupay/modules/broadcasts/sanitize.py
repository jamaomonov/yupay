"""Telegram-HTML whitelist validator for admin-authored broadcast bodies.

Pure, I/O-free module: no DB, no network. This is the save-time chokepoint — a body that
passes :func:`validate_body` is guaranteed safe to send to Telegram's HTML parse mode, so a
malformed body never reaches the fan-out job. Built on the stdlib ``html.parser.HTMLParser``
(no new dependency); tag/attribute names it reports are already lower-cased, including the
custom tag name ``tg-spoiler``.

``HTMLParser`` is constructed with ``convert_charrefs=True`` (the default), which decodes
character references (``&amp;`` etc.) exactly once before handing text to ``handle_data`` —
callers must not run ``html.unescape`` again on that output, or entities get double-decoded
and the visible-length ceiling can be defeated by nesting entities (e.g. ``&amp;amp;``).

``HTMLParser`` also silently no-ops comments (``<!-- ... -->``), processing instructions
(``<?...?>``), and declarations (``<!...>``) by default — none of them reach
``handle_starttag``/``handle_endtag``, and an *unterminated* comment swallows everything to
EOF, including any disallowed markup inside it. ``_TelegramHtmlValidator`` overrides those
handlers to reject explicitly, and ``validate_body`` additionally rejects up front on a raw
``<!`` or ``<?`` substring so an unterminated comment/PI (which never reaches the handler) is
still caught — valid Telegram HTML never contains a literal ``<!`` or ``<?``.

Likewise, an unterminated *ordinary* tag or attribute (e.g. ``<b class="`` with no closing
``"`` or ``>``) never reaches ``handle_starttag`` either — ``HTMLParser`` buffers it as an
incomplete construct and, on ``close()``, discards it with no callback at all, silently
swallowing everything after it to EOF (counted as ~0 visible chars). ``_TelegramHtmlValidator``
guards against this by checking its own ``rawdata`` buffer immediately after ``feed()`` —
*before* calling ``close()``, which would otherwise erase the signal — and specifically for a
leftover ``<`` in that buffer, since a benign trailing character reference (e.g. a body ending
in a bare ``&`` or an incomplete ``&amp`` with no terminator) is *also* held back in
``rawdata`` until EOF but never contains a ``<``, and must be tolerated as plain text.
"""

from __future__ import annotations

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

    Strips every tag; HTML entities are decoded exactly once, by the underlying parser's
    ``convert_charrefs=True`` behavior — this is the count Telegram's caption/message length
    limits are enforced against, not the length of the raw markup.

    Assumes structurally-valid input (balanced tags, no incomplete/unterminated markup) —
    it is normally called only after :func:`validate_body`'s own parse has already gated on
    that, so a direct caller bypassing that gate can get an undercount on malformed input
    (an unterminated tag silently swallows the rest of the body as ~0 visible chars).
    """
    collector = _TextCollector()
    collector.feed(html)
    collector.close()
    return len(collector.text)


class _TelegramHtmlValidator(HTMLParser):
    """Validates a Telegram-HTML body against :data:`ALLOWED_TAGS`.

    Tracks an open-tag stack: every start tag must be allowed, ``a`` must carry exactly an
    ``href`` attribute whose scheme is in ``{http, https, tg}``, every other allowed tag must
    carry no attributes at all, and every end tag must close the innermost open tag. Comments,
    processing instructions, and declarations are rejected outright — none of them are part of
    Telegram's HTML subset, and ``HTMLParser`` would otherwise no-op them by default (silently
    hiding whatever markup they contain). Anything disallowed raises :class:`ValidationError`
    immediately, from inside the parser callback.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._stack: list[str] = []

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

    def handle_comment(self, data: str) -> None:  # noqa: ARG002 -- override, content irrelevant
        raise ValidationError("HTML comments are not allowed in a broadcast body")

    def handle_pi(self, data: str) -> None:  # noqa: ARG002 -- override, content irrelevant
        raise ValidationError(
            "processing instructions are not allowed in a broadcast body"
        )

    def handle_decl(self, decl: str) -> None:  # noqa: ARG002 -- override, content irrelevant
        raise ValidationError("HTML declarations are not allowed in a broadcast body")

    def unknown_decl(self, data: str) -> None:  # noqa: ARG002 -- override, content irrelevant
        raise ValidationError("unknown declarations are not allowed in a broadcast body")

    def finish(self) -> None:
        """Finalize parsing after ``feed()``.

        Checks ``self.rawdata`` *before* calling ``close()``: an incomplete construct at
        the end of the fed input (an unterminated tag, e.g. ``<b`` or an unclosed
        attribute-quote, e.g. ``<b class="...`` with no closing ``"`` or ``>``) is left
        unconsumed in ``rawdata`` by ``feed()``, without ever reaching
        ``handle_starttag``/``handle_data`` — so it would otherwise swallow the rest of the
        body silently (counted as ~0 visible chars) and evade both the tag stack and the
        length ceiling. Calling ``close()`` first would erase this signal: ``HTMLParser``
        forces end-of-stream parsing there and *silently discards* an unterminated
        start-tag construct, resetting ``rawdata`` back to ``""`` with no callback at all —
        so the check must happen first, or the bypass is invisible.

        The check is narrowed to leftovers that *contain* a ``<``: with
        ``convert_charrefs=True``, ``HTMLParser`` also holds back a trailing, not-yet-
        disambiguated character reference (e.g. a body ending in a bare ``&`` or an
        incomplete named entity like ``&amp`` with no terminator) in ``rawdata`` until EOF,
        purely because it *could* still turn into a longer entity if more input arrived.
        That is benign, plain text — a literal ``&`` is meant to be tolerated (Telegram's
        HTML mode doesn't require escaping it) — and must not be rejected. A genuine
        incomplete tag/comment/PI leftover always starts at the unclosed ``<...`` construct,
        so it always contains a ``<``; a benign trailing-entity leftover never does.

        Raises:
            ValidationError: if the fed input ends with an incomplete/unterminated tag,
                comment, or processing instruction (a ``<`` left unconsumed in the
                buffer), or if any tag was left open (unbalanced markup).
        """
        if "<" in self.rawdata:
            raise ValidationError("incomplete or unterminated markup at end of body")
        self.close()
        if self._stack:
            raise ValidationError(f"unclosed tag: <{self._stack[-1]}>")


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
            unbalanced or mis-nested tags, a comment/declaration/processing instruction, or a
            visible length over the applicable ceiling.
    """
    # Belt-and-suspenders for CRITICAL-1: a *terminated* comment/PI/decl is caught by the
    # parser callbacks below, but an *unterminated* one (e.g. an unclosed `<!--`) swallows
    # everything to EOF and never reaches those callbacks at all. Valid Telegram HTML never
    # contains a literal `<!` or `<?`, so reject on the raw substring up front too.
    if "<!" in html or "<?" in html:
        raise ValidationError(
            "HTML comments, declarations, and processing instructions are not allowed"
        )
    validator = _TelegramHtmlValidator()
    validator.feed(html)
    validator.finish()
    limit = _CAPTION_LIMIT if has_media else _MESSAGE_LIMIT
    length = visible_length(html)
    if length > limit:
        kind = "caption" if has_media else "message"
        raise ValidationError(
            f"body is {length} visible characters, over the {kind} limit of {limit}"
        )


__all__ = ["ALLOWED_TAGS", "validate_body", "visible_length"]
