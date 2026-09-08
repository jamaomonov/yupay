"""The destination half of :mod:`yupay.core.outbound`: parse it, then aim it.

Nothing here does I/O. It turns a merchant's configured URL into a
destination that can be sent to, and refuses the ones that must not be sent
to at all — before a single packet moves. Aiming the request at the checked
address is the client's job (``outbound._pinned_url``), because that needs
the address, which needs the resolver.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final
from urllib.parse import urlsplit

from yupay.core.outbound_errors import UrlNotAllowedError

#: The port a URL without one means, and the one a ``Host`` header omits.
HTTPS_PORT: Final = 443


@dataclass(frozen=True, slots=True)
class Target:
    """A destination parsed out of the caller's URL, before any resolution."""

    host: str
    port: int
    authority: str
    path: str


def _ascii_host(hostname: str) -> str:
    """The host as it goes on the wire: lowercased, undotted, IDNA-encoded.

    Everything downstream — ``getaddrinfo``, the ``Host`` header, the TLS
    server name — wants ASCII, and a merchant may legitimately configure
    ``https://пример.рф/hook``, which the save-time validator accepts. So this
    encodes rather than refuses, and turns the two ways that can fail into the
    module's own typed refusal: a label that will not encode, and a label over
    63 characters (``UnicodeError``, which is a ``ValueError`` and so slips
    straight past an ``except OSError`` further down).

    Args:
        hostname: ``urlsplit``'s hostname, already lowercased by it.

    Returns:
        The A-label form, or the original when it is already ASCII.

    Raises:
        UrlNotAllowedError: Empty, or not encodable as a domain name.
    """
    host = hostname.rstrip(".")
    if not host:
        raise UrlNotAllowedError("the destination must have a host")
    if host.isascii():
        # Left as-is on purpose: the IDNA codec would also reject spellings
        # ``getaddrinfo`` accepts, and an over-long ASCII label is caught
        # where the lookup happens.
        return host
    try:
        return host.encode("idna").decode("ascii")
    except ValueError as exc:
        # ``UnicodeError`` — which is what the codec actually raises for an
        # empty or over-long label — is a ``ValueError``.
        raise UrlNotAllowedError("the destination's host is not a usable domain name") from exc


def parse_target(url: str) -> Target:
    """Split ``url`` into a destination, refusing anything we will not send to.

    No part of ``url`` appears in the errors raised here: a merchant's webhook
    URL can carry a token in its query, and an exception message ends up in a
    log line and in the delivery row.

    Args:
        url: The caller's destination URL.

    Returns:
        The parsed target.

    Raises:
        UrlNotAllowedError: Not https, carrying URL credentials, hostless,
            aimed at port 0, or carrying a host no lookup could be made from.
    """
    try:
        parsed = urlsplit(url)
        scheme, username, password = parsed.scheme, parsed.username, parsed.password
        hostname, raw_port = parsed.hostname, parsed.port
    except ValueError as exc:
        # ``urlsplit`` itself is lenient, but reading ``.port`` (and IPv6
        # bracket handling) raises on malformed authorities.
        raise UrlNotAllowedError("the destination is not a URL we can parse") from exc
    if scheme != "https":
        raise UrlNotAllowedError("the destination must use https")
    if username or password:
        raise UrlNotAllowedError("the destination must not carry credentials in its URL")
    host = _ascii_host(hostname or "")
    port = HTTPS_PORT if raw_port is None else raw_port
    if port == 0:
        # ``parsed.port or 443`` used to turn this into 443 and deliver
        # somewhere the merchant never named. Port 0 is not a destination.
        raise UrlNotAllowedError("the destination's port must not be 0")
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    # ``hostname`` strips the brackets an IPv6 literal is written with; the
    # Host header has to put them back or the authority is unparseable.
    written = f"[{host}]" if ":" in host else host
    return Target(
        host=host,
        port=port,
        authority=written if port == HTTPS_PORT else f"{written}:{port}",
        path=path,
    )


__all__ = ["HTTPS_PORT", "Target", "parse_target"]
