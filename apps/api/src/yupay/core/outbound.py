"""Outbound HTTP to an address a third party chose, checked at connect time.

``apps/worker`` runs inside our Docker network, beside Postgres, Redis and
MinIO. From M3a it POSTs merchant webhooks to a URL the **merchant** supplies,
which is a request to make our own worker probe our own private network unless
something stops it. This module is that something.

Why it exists rather than reusing the save-time check:
:mod:`yupay.modules.catalog.image_url_safety` validates a URL when it is
stored and says in its own docstring that it cannot catch **DNS rebinding** —
a host that answers with a public address while the validator runs and a
private one when the fetch happens — because Next's image optimizer owns that
fetcher and offers no hook. Here we own the fetcher. The two are deliberately
**not** the same function: that one parses *notation* at save time, this one
checks *resolved addresses* at connect time, and folding them together would
let an edit to one silently change the other.

How the address is pinned:

1. Resolve the host once, ourselves.
2. Refuse unless **every** answer is public — a host with one public and one
   private record is refused, not raced. The first answer is then the one
   used, with **no fallback to the others** if it does not connect: a second
   attempt would have to know whether the first one had already put the
   request on the wire, and a wrong answer there delivers a webhook twice.
   (``resolve_addresses`` asks for ``AI_ADDRCONFIG`` so "the first answer" is
   one this host can actually route to.)
3. Build the request against the chosen address as a **literal**, carrying the
   original hostname in the ``Host`` header and in TLS SNI (so certificate
   verification still happens against the name, not the address).
4. Watch httpcore's ``connect_tcp`` trace and refuse if the host handed to the
   socket layer is ever not that address. Step 3 is the mechanism; step 4 is
   what makes it an invariant rather than a convention, so a later edit that
   reintroduces connect-by-name fails closed.

Connections are never pooled across calls: each call builds its own client and
closes it. A reused connection would skip steps 1-4 for every request after
the first, which is the same hole by a slower route.

Refusals are typed and split into two families, because the caller records
them as different delivery outcomes: :class:`OutboundRefusedError` means *we*
refused, :class:`OutboundUnreachableError` means *their server did not
answer*.

The client never logs the body it sends, the headers it sends, or the URL —
a merchant's webhook URL may carry a token in its query, and the signature
header authorises the delivery. Exception messages follow the same rule.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import ssl
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Final
from urllib.parse import urlsplit

import httpx

from yupay.core.logging import get_logger
from yupay.core.outbound_addresses import blocked_reason, resolve_addresses

log = get_logger("yupay.core.outbound")

#: Wall-clock budget for one delivery attempt, DNS included. It is a total,
#: not a per-phase timeout: a server that drips one byte every second would
#: never trip a read timeout and would hold a worker slot for as long as it
#: liked.
DEFAULT_TIMEOUT_SECONDS: Final = 10.0

#: How much of a response we are willing to read. Anything a merchant's
#: endpoint has to say about a webhook fits many times over.
DEFAULT_MAX_BYTES: Final = 64 * 1024

_HTTPS_PORT: Final = 443

#: httpcore's trace event for "about to open a TCP connection to this host".
#: Pinned by :func:`_connect_guard` and asserted by the live test suite, so an
#: httpcore upgrade that renames it fails a test rather than silently
#: disarming the guard.
_CONNECT_TRACE_EVENT: Final = "connection.connect_tcp.started"


class OutboundError(Exception):
    """Base class for everything :func:`post_json` raises."""


class OutboundRefusedError(OutboundError):
    """**We** refused. The merchant's server is not at fault and not at risk.

    A caller recording delivery outcomes should treat this as "blocked by
    policy" rather than "the endpoint failed": retrying changes nothing until
    the merchant changes the URL or their DNS.
    """


class UrlNotAllowedError(OutboundRefusedError):
    """The URL was refused before anything was resolved or connected to."""


class AddressNotAllowedError(OutboundRefusedError):
    """A resolved address is not one we will connect to.

    Attributes:
        host: The hostname that resolved to it.
        reasons: One ``"<address>: <family>"`` string per offending answer.
    """

    def __init__(self, message: str, *, host: str = "", reasons: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.host = host
        self.reasons = reasons


class ResponseTooLargeError(OutboundRefusedError):
    """The response passed ``max_bytes`` and the read was cut off.

    Note for the caller: the request **was** delivered — their server received
    it and answered. Retrying it re-delivers. Treat this as terminal.
    """


class OutboundUnreachableError(OutboundError):
    """**They** did not answer. Nothing was refused by us; a retry may work."""


class ResolutionFailedError(OutboundUnreachableError):
    """The hostname did not resolve at all."""


class ConnectFailedError(OutboundUnreachableError):
    """The connection, the TLS handshake, or the exchange itself failed."""


class OutboundTimeoutError(OutboundUnreachableError):
    """The attempt passed its total wall-clock budget."""


@dataclass(frozen=True, slots=True)
class OutboundResponse:
    """What one delivery attempt produced, sized for a delivery-log row.

    Attributes:
        status_code: Whatever they answered, redirects included — a 30x is an
            outcome here, never a hop.
        body: Their response, decoded with replacement and never longer than
            the call's ``max_bytes``. For a human reading the log, not for
            parsing.
        address: The address the request was actually sent to. Worth storing:
            "we recorded a 502 — from which of their hosts?" is otherwise
            unanswerable.
        elapsed_ms: Wall clock for the whole attempt, DNS included.
    """

    status_code: int
    body: str
    address: str
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class _Target:
    """A destination parsed out of the caller's URL, before any resolution."""

    host: str
    port: int
    authority: str
    path: str


def _parse_target(url: str) -> _Target:
    """Split ``url`` into a destination, refusing anything we will not send to.

    No part of ``url`` appears in the errors raised here: a merchant's webhook
    URL can carry a token in its query, and an exception message ends up in a
    log line and in the delivery row.

    Args:
        url: The caller's destination URL.

    Returns:
        The parsed target.

    Raises:
        UrlNotAllowedError: Not https, carrying URL credentials, or hostless.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise UrlNotAllowedError("the destination must use https")
    if parsed.username or parsed.password:
        raise UrlNotAllowedError("the destination must not carry credentials in its URL")
    host = (parsed.hostname or "").rstrip(".")
    if not host:
        raise UrlNotAllowedError("the destination must have a host")
    try:
        port = parsed.port or _HTTPS_PORT
    except ValueError as exc:
        raise UrlNotAllowedError("the destination's port is not a number") from exc
    path = parsed.path or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"
    # ``hostname`` strips the brackets an IPv6 literal is written with; the
    # Host header has to put them back or the authority is unparseable.
    written = f"[{host}]" if ":" in host else host
    return _Target(
        host=host,
        port=port,
        authority=written if port == _HTTPS_PORT else f"{written}:{port}",
        path=path,
    )


def _reject_unless_every_address_is_public(host: str, addresses: tuple[str, ...]) -> None:
    """Refuse the host outright if **any** of its addresses is not public.

    Not "pick the public one": a host that answers with one public and one
    private address is a host we have no business connecting to, and choosing
    among the answers would make the outcome a race between resolutions.

    Args:
        host: The hostname, for the message.
        addresses: Every answer from :func:`~yupay.core.outbound_addresses.resolve_addresses`.

    Raises:
        AddressNotAllowedError: At least one answer is blocked or unreadable.
    """
    findings: list[str] = []
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            # Fail closed. A scoped literal (``fe80::1%eth0``) lands here, and
            # so would anything else the policy cannot read.
            findings.append(f"{address}: unreadable")
            continue
        reason = blocked_reason(ip)
        if reason is not None:
            findings.append(f"{address}: {reason}")
    if findings:
        raise AddressNotAllowedError(
            f"{host} resolves to an address we will not connect to — {'; '.join(findings)}",
            host=host,
            reasons=tuple(findings),
        )


def _pinned_url(target: _Target, address: str) -> str:
    """The request URL, aimed at ``address`` rather than at the hostname."""
    literal = f"[{address}]" if ":" in address else address
    netloc = literal if target.port == _HTTPS_PORT else f"{literal}:{target.port}"
    return f"https://{netloc}{target.path}"


def _connect_guard(
    *, pinned: str, host: str
) -> Callable[[str, Mapping[str, Any]], Awaitable[None]]:
    """A trace hook that refuses any socket target other than ``pinned``.

    httpx builds the connection from the URL, so aiming the URL at the checked
    address is what pins it; this watches the layer below and turns that into
    something a future edit cannot quietly undo. It fails **closed** on a
    mismatch. It does not require having been called — an httpcore release
    that renames the trace event would otherwise take webhook delivery down
    rather than degrade it, which is why the live suite asserts the event name
    instead.

    Args:
        pinned: The address the policy cleared.
        host: The hostname, for the message.

    Returns:
        An async callback for httpx's ``trace`` request extension.
    """

    async def _trace(event: str, info: Mapping[str, Any]) -> None:
        if event != _CONNECT_TRACE_EVENT:
            return
        target = str(info.get("host", ""))
        if target != pinned:
            raise AddressNotAllowedError(
                f"refusing to connect: the socket target {target!r} is not the "
                f"checked address {pinned!r} for {host}",
                host=host,
            )

    return _trace


@lru_cache(maxsize=1)
def _ssl_context() -> ssl.SSLContext:
    """The verifying TLS context, built once and shared."""
    return httpx.create_ssl_context()


def _build_client(*, timeout: float) -> httpx.AsyncClient:
    """A single-use client for one delivery attempt.

    ``trust_env=False`` is load-bearing, not tidiness: a ``HTTPS_PROXY`` in
    the worker's environment would have the proxy resolve the destination by
    name on our behalf, which discards the pin and every check behind it.
    ``follow_redirects=False`` is the same idea one layer up.
    """
    return httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        trust_env=False,
        verify=_ssl_context(),
        limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
    )


def _outgoing_headers(target: _Target, headers: Mapping[str, str] | None) -> httpx.Headers:
    """The caller's headers, plus the three this module owns."""
    out = httpx.Headers(dict(headers) if headers else {})
    out.setdefault("content-type", "application/json")
    # Identity, so ``max_bytes`` bounds what we decompress as well as what we
    # read — a compressed bomb cannot expand past the cap.
    out["accept-encoding"] = "identity"
    # Last, so the caller cannot detach the Host header from the pinned name.
    out["host"] = target.authority
    return out


async def _read_capped(response: httpx.Response, *, max_bytes: int, host: str) -> bytes:
    """Read a streamed response, stopping the moment it passes the cap.

    Raises:
        ResponseTooLargeError: The body passed ``max_bytes``.
    """
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(
                f"the response from {host} passed the {max_bytes}-byte cap and was cut off"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _send(
    target: _Target,
    pinned: str,
    *,
    body: bytes,
    headers: Mapping[str, str] | None,
    timeout: float,
    max_bytes: int,
) -> tuple[int, bytes]:
    """Send one request to the pinned address and read a bounded response."""
    client = _build_client(timeout=timeout)
    try:
        request = client.build_request(
            "POST",
            _pinned_url(target, pinned),
            content=body,
            headers=_outgoing_headers(target, headers),
            extensions={
                "sni_hostname": target.host,
                "trace": _connect_guard(pinned=pinned, host=target.host),
            },
        )
        try:
            response = await client.send(request, stream=True)
            try:
                raw = await _read_capped(response, max_bytes=max_bytes, host=target.host)
            finally:
                # Closing a stream we abandoned mid-body can fail on its own;
                # that must not replace the refusal that abandoned it.
                with contextlib.suppress(httpx.HTTPError):
                    await response.aclose()
        except httpx.TimeoutException as exc:
            raise OutboundTimeoutError(f"{target.host} did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise ConnectFailedError(
                f"{target.host} could not be reached: {type(exc).__name__}"
            ) from exc
        return response.status_code, raw
    finally:
        await client.aclose()


async def post_json(
    url: str,
    *,
    body: bytes,
    headers: Mapping[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> OutboundResponse:
    """POST ``body`` to ``url``, connecting only to an address checked first.

    ``body`` is **bytes**, not an object to serialise: the caller signs what it
    sends, so the bytes it signed have to be the bytes that go on the wire.
    ``content-type: application/json`` is set unless the caller sets it.

    Redirects are never followed (a 30x comes back as a result), the response
    is read only up to ``max_bytes``, and ``timeout`` is a total budget over
    resolution, connection and reading.

    Args:
        url: The destination. Must be ``https`` and must not carry credentials.
        body: The exact request body.
        headers: Extra request headers. ``Host`` cannot be overridden.
        timeout: Total wall-clock budget in seconds.
        max_bytes: Cap on the response body.

    Returns:
        The status, the response text, the address used and the elapsed time.

    Raises:
        UrlNotAllowedError: The URL itself is refused (nothing is contacted).
        AddressNotAllowedError: The host resolves to a non-public address, or
            the socket layer was handed something other than the checked one.
        ResponseTooLargeError: They answered with more than ``max_bytes``.
        ResolutionFailedError: The host did not resolve.
        ConnectFailedError: The connection or the exchange failed.
        OutboundTimeoutError: The attempt passed ``timeout``.
    """
    target = _parse_target(url)
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout):
            try:
                addresses = await resolve_addresses(target.host, target.port)
            except OSError as exc:
                raise ResolutionFailedError(f"{target.host} did not resolve") from exc
            if not addresses:
                raise ResolutionFailedError(f"{target.host} resolved to no addresses")
            _reject_unless_every_address_is_public(target.host, addresses)
            pinned = addresses[0]
            status_code, raw = await _send(
                target,
                pinned,
                body=body,
                headers=headers,
                timeout=timeout,
                max_bytes=max_bytes,
            )
    except TimeoutError as exc:
        raise OutboundTimeoutError(f"{target.host} did not answer within {timeout}s") from exc
    except OutboundRefusedError as exc:
        log.warning("outbound.refused", host=target.host, refusal=type(exc).__name__)
        raise
    elapsed_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "outbound.delivered",
        host=target.host,
        address=pinned,
        status_code=status_code,
        elapsed_ms=elapsed_ms,
        response_bytes=len(raw),
    )
    return OutboundResponse(
        status_code=status_code,
        body=raw.decode("utf-8", errors="replace"),
        address=pinned,
        elapsed_ms=elapsed_ms,
    )


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "AddressNotAllowedError",
    "ConnectFailedError",
    "OutboundError",
    "OutboundRefusedError",
    "OutboundResponse",
    "OutboundTimeoutError",
    "OutboundUnreachableError",
    "ResolutionFailedError",
    "ResponseTooLargeError",
    "UrlNotAllowedError",
    "post_json",
]
