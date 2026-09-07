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
   private record is refused, not raced. "Every answer" means every answer the
   resolver gave us: ``resolve_addresses`` asks for ``AI_ADDRCONFIG``, so a
   family this host cannot route (AAAA on an IPv4-only container) is not
   returned and therefore not judged. A dual-stack merchant with a public A
   and a private AAAA is delivered to there rather than refused — the address
   we would have refused is one nothing here could have reached.
3. The first answer is the one used, with **no fallback to the others** if it
   does not connect: a second attempt would have to know whether the first had
   already put the request on the wire, and being wrong about that delivers a
   webhook twice.
4. Build the request against the chosen address as a **literal**, carrying the
   original hostname in the ``Host`` header and in TLS SNI (so certificate
   verification still happens against the name, not the address).
5. Watch httpcore's ``connect_tcp`` trace and refuse if the host handed to the
   socket layer is ever not that address. Step 4 is the mechanism; step 5 is
   what makes it an invariant rather than a convention, so a later edit that
   reintroduces connect-by-name fails closed.

Connections are never pooled across calls: each call builds its own client and
closes it. A reused connection would skip steps 1-5 for every request after
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

import httpx

from yupay.core.logging import get_logger
from yupay.core.outbound_addresses import blocked_reason, resolve_addresses
from yupay.core.outbound_errors import (
    AddressNotAllowedError,
    ConnectFailedError,
    ContentEncodingNotAllowedError,
    Delivery,
    ExchangeFailedError,
    OutboundBrokenError,
    OutboundError,
    OutboundRefusedError,
    OutboundTimeoutError,
    OutboundUnreachableError,
    ResolutionFailedError,
    ResponseTooLargeError,
    UrlNotAllowedError,
)
from yupay.core.outbound_target import HTTPS_PORT, Target, parse_target

log = get_logger("yupay.core.outbound")

#: Wall-clock budget for one delivery attempt, DNS included. It is a total,
#: not a per-phase timeout: a server that drips one byte every second would
#: never trip a read timeout and would hold a worker slot for as long as it
#: liked.
DEFAULT_TIMEOUT_SECONDS: Final = 10.0

#: How much of a response we are willing to read. Anything a merchant's
#: endpoint has to say about a webhook fits many times over.
DEFAULT_MAX_BYTES: Final = 64 * 1024

#: Cap on the ``Retry-After`` value we carry back. It is text a third party
#: wrote, so it is bounded where it is read rather than wherever it lands: the
#: two forms that mean anything are a short integer and a 29-character
#: HTTP-date, and nothing downstream should have to cope with more.
_RETRY_AFTER_MAX: Final = 64

#: httpcore's trace event for "about to open a TCP connection to this host".
#: Pinned by :func:`_connect_guard` and asserted by the live test suite, so an
#: httpcore upgrade that renames it fails a test rather than silently
#: disarming the guard.
_CONNECT_TRACE_EVENT: Final = "connection.connect_tcp.started"


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
        retry_after: Their ``Retry-After`` header, verbatim and clipped to
            :data:`_RETRY_AFTER_MAX`, or ``None``. The **only** response
            header surfaced, and it is here because a retry policy that
            ignores a ``429``'s own answer to "when should I come back" is
            hammering a server that asked it not to. Handing a caller the
            whole header map would put a merchant's (or their compromised
            server's) arbitrary text in front of code that has no use for it;
            parsing this one — both RFC forms, and a clamp — is the caller's
            job (``merchants.webhook_retry.parse_retry_after``).
    """

    status_code: int
    body: str
    address: str
    elapsed_ms: int
    retry_after: str | None = None


async def _resolve_or_fail(target: Target) -> tuple[str, ...]:
    """Resolve ``target``, turning every way a lookup can fail into one type.

    Args:
        target: The parsed destination.

    Returns:
        Every address the resolver returned, in its order.

    Raises:
        ResolutionFailedError: The lookup failed or answered with nothing.
    """
    try:
        addresses = await resolve_addresses(target.host, target.port)
    except (OSError, UnicodeError) as exc:
        # ``UnicodeError`` is a ``ValueError``, not an ``OSError``: getaddrinfo
        # raises it for any DNS label over 63 characters, ASCII included, and
        # it used to escape this module untyped.
        raise ResolutionFailedError(f"{target.host} did not resolve") from exc
    if not addresses:
        raise ResolutionFailedError(f"{target.host} resolved to no addresses")
    return addresses


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
            # Fail closed on anything ``ipaddress`` will not read, rather than
            # skipping it and checking the rest. (A scoped literal such as
            # ``fe80::1%eth0`` is NOT one of those — ``ipaddress`` has parsed
            # those since 3.9 and it lands as link-local like any other
            # ``fe80::/10`` address.)
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


def _pinned_url(target: Target, address: str) -> str:
    """The request URL, aimed at ``address`` rather than at the hostname."""
    literal = f"[{address}]" if ":" in address else address
    netloc = literal if target.port == HTTPS_PORT else f"{literal}:{target.port}"
    return f"https://{netloc}{target.path}"


# ``Mapping[str, Any]`` because httpcore's trace payload is a plain dict whose
# values differ per event (a host string here, a stream object there) and it
# publishes no type for it. The only key read is ``host``, and it is
# ``str()``-ed before it is compared.
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


def _outgoing_headers(target: Target, headers: Mapping[str, str] | None) -> httpx.Headers:
    """The caller's headers, plus the three this module owns."""
    out = httpx.Headers(dict(headers) if headers else {})
    out.setdefault("content-type", "application/json")
    # Ask for an undecoded body. This is the polite half of the compression
    # defence and not the load-bearing one — a server can ignore it, which is
    # why ``_read_capped`` reads raw bytes and refuses an encoded response.
    out["accept-encoding"] = "identity"
    # Last, so the caller cannot detach the Host header from the pinned name.
    out["host"] = target.authority
    return out


async def _read_capped(response: httpx.Response, *, max_bytes: int, host: str) -> bytes:
    """Read a streamed response off the wire, stopping the moment it passes the cap.

    ``aiter_raw`` and not ``aiter_bytes``, which is the whole point:
    ``aiter_bytes`` runs httpx's decoder, which decompresses on the
    **response's** ``Content-Encoding`` no matter what we asked for, and the
    cap would then be counting already-expanded bytes. A 300 KB gzip answer
    reached ~50 MB of heap that way, independent of ``max_bytes``. Reading raw
    makes the cap a bound on what actually crosses the socket, so a
    compression bomb cannot expand inside this process at all — and an encoded
    body is refused below rather than handed back undecoded.

    The refusal below and this raw read are **deliberately redundant**: today
    the refusal fires first and nothing reaches the loop with an encoding on
    it, so the raw read is doing no work a decoded read would not have done.
    It is here for the day someone relaxes the refusal for a merchant whose
    server gzips everything — at which point this is the only thing standing
    between us and an attacker-chosen expansion ratio. A test asserts the
    decoder is never even constructed, so the redundancy cannot rot into a
    comment that used to be true.

    Note that ``brotli``/``zstandard`` are not installed, so httpx cannot
    decode those today. That is not what makes this safe, and installing
    either must not be read as re-opening the question: the guarantee here is
    that nothing is decoded, not that we lack a decoder.

    Raises:
        ResponseTooLargeError: The body passed ``max_bytes`` on the wire.
        ContentEncodingNotAllowedError: They compressed it anyway.
    """
    encoding = response.headers.get("content-encoding", "").strip().lower()
    if encoding not in {"", "identity"}:
        # Before reading a byte of it. We asked for identity; a server that
        # compresses anyway is either misbehaving or aiming a bomb.
        raise ContentEncodingNotAllowedError(
            f"{host} answered with a {encoding!r}-encoded body, which is not decoded here"
        )
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.aiter_raw():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(
                f"the response from {host} passed the {max_bytes}-byte cap and was cut off"
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _send(
    target: Target,
    pinned: str,
    *,
    body: bytes,
    headers: Mapping[str, str] | None,
    timeout: float,
    max_bytes: int,
) -> tuple[int, bytes, str | None]:
    """Send one request to the pinned address and read a bounded response.

    Returns:
        The status, the capped body bytes, and their ``Retry-After`` header
        (clipped, or ``None``) — see :class:`OutboundResponse`.

    Note for a caller that logs this module's exceptions: the ``__cause__``
    chained onto :class:`ConnectFailedError` is an ``httpx.RequestError``
    whose ``.request`` holds the **pinned URL, query included**. Nothing here
    puts that in a message, but ``exc_info=True`` with request context can
    surface a token a merchant put in their webhook query. Log the type and
    the host, not the chained request.
    """
    client = _build_client(timeout=timeout)
    try:
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
        except OutboundError:
            raise
        except Exception as exc:
            # Building a request is not I/O, so everything that can fail here
            # is about what we were handed: an un-encodable header value, a
            # URL httpx will not take. Untyped, it would escape the whole
            # module and poison a queue drain that catches ``OutboundError``.
            raise UrlNotAllowedError(
                f"no request could be built for {target.host}: {type(exc).__name__}"
            ) from exc
        try:
            response = await client.send(request, stream=True)
            try:
                raw = await _read_capped(response, max_bytes=max_bytes, host=target.host)
            finally:
                # Closing a stream we abandoned mid-body can fail on its own;
                # that must not replace the refusal that abandoned it.
                with contextlib.suppress(httpx.HTTPError):
                    await response.aclose()
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Nothing was written: the socket or the handshake never came up.
            # This is the only transport failure a caller may retry blindly,
            # which is why it is a different type from the ones below.
            #
            # Ordered BEFORE ``TimeoutException`` on purpose: ``ConnectTimeout``
            # is a subclass of it, so the other order makes this clause dead
            # for the commonest way a socket never comes up, and a handshake
            # timeout is then reported as UNKNOWN instead of NOT_SENT.
            raise ConnectFailedError(
                f"{target.host} could not be reached: {type(exc).__name__}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise OutboundTimeoutError(f"{target.host} did not answer in time") from exc
        except httpx.HTTPError as exc:
            raise ExchangeFailedError(
                f"the exchange with {target.host} failed: {type(exc).__name__}"
            ) from exc
        retry_after = response.headers.get("retry-after")
        return (
            response.status_code,
            raw,
            retry_after[:_RETRY_AFTER_MAX] if retry_after is not None else None,
        )
    finally:
        # Suppressed for the same reason as the response close above: a
        # failure to hang up must not replace the failure being reported.
        with contextlib.suppress(httpx.HTTPError):
            await client.aclose()


def _log_broken(exc: BaseException, *, host: str) -> None:
    """Report an unexpected failure without rendering the exception chain.

    Not ``log.exception``: that renders every ``__cause__`` under it, and
    :func:`_send`'s docstring warns the caller off exactly that, because an
    httpx error down the chain holds the pinned URL with its query. Reaching
    here is a bug in this module and nothing above will report it, so the
    type and the innermost frame are logged instead — enough to find it, and
    nothing that carries a merchant's token.
    """
    frame = exc.__traceback__
    while frame is not None and frame.tb_next is not None:
        frame = frame.tb_next
    where = f"{frame.tb_frame.f_code.co_filename}:{frame.tb_lineno}" if frame else "unknown"
    log.error("outbound.broken", host=host, failure=type(exc).__name__, where=where)


def _parse_or_broken(url: str) -> Target:
    """:func:`parse_target`, with the same total-typing guarantee as the rest.

    Nothing but a non-``str`` argument gets past mypy into the untyped half
    today, but the module docstring promises every path out of
    :func:`post_json` is an :class:`OutboundError`, and a promise with one
    unguarded call in front of it is not one.
    """
    try:
        return parse_target(url)
    except OutboundError:
        raise
    except Exception as exc:
        _log_broken(exc, host="<unparsed>")
        raise OutboundBrokenError(
            f"the destination could not be parsed: {type(exc).__name__}"
        ) from exc


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
        The status, the response text, the address used, the elapsed time and
        their ``Retry-After`` header if they sent one.

    Raises:
        UrlNotAllowedError: The URL itself is refused, or no request could be
            built from it (nothing is contacted either way).
        AddressNotAllowedError: The host resolves to a non-public address, or
            the socket layer was handed something other than the checked one.
        ResponseTooLargeError: They answered with more than ``max_bytes`` on
            the wire.
        ContentEncodingNotAllowedError: They answered with a compressed body.
        ResolutionFailedError: The host did not resolve.
        ConnectFailedError: The socket or the TLS handshake never came up —
            the one transport failure that is safe to retry blindly.
        ExchangeFailedError: The connection came up and the exchange broke,
            so the request may already have been written.
        OutboundTimeoutError: The attempt passed ``timeout``.
        OutboundBrokenError: Anything else at all — every path out of here is
            one of these, so a queue drain catching :class:`OutboundError`
            cannot be handed an untyped exception.
    """
    target = _parse_or_broken(url)
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout):
            addresses = await _resolve_or_fail(target)
            _reject_unless_every_address_is_public(target.host, addresses)
            pinned = addresses[0]
            status_code, raw, retry_after = await _send(
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
    except OutboundUnreachableError:
        raise
    except Exception as exc:
        # The net that makes ``OutboundError`` total (see its docstring). Only
        # ``Exception``, so a cancellation still cancels.
        _log_broken(exc, host=target.host)
        raise OutboundBrokenError(
            f"the attempt to {target.host} broke: {type(exc).__name__}"
        ) from exc
    elapsed_ms = int((time.monotonic() - started) * 1000)
    log.info(
        "outbound.delivered",
        host=target.host,
        # The merchant's server address, not a person's — AGENTS §9's
        # never-log list means an end user's IP. The delivery log's whole
        # question is "which of their hosts answered", and the pin is what
        # makes that answerable.
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
        retry_after=retry_after,
    )


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "AddressNotAllowedError",
    "ConnectFailedError",
    "ContentEncodingNotAllowedError",
    "Delivery",
    "ExchangeFailedError",
    "OutboundBrokenError",
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
