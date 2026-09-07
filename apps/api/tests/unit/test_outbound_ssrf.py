"""Unit tests for the SSRF-safe outbound client (M3a, Task 2).

No sockets here: DNS is stubbed and the HTTP transport is an
``httpx.MockTransport``, so every test in this file is hermetic and fast.
The half that needs real sockets — a TLS server on a loopback port, and the
proof that the connection lands on the address the policy checked — is
``tests/integration/test_outbound_ssrf_live.py``.

What is being defended: ``apps/worker`` runs inside our Docker network,
beside Postgres, Redis and MinIO, and M3a has it POST to a URL a **merchant**
chose. ``modules/catalog/image_url_safety.py`` validates that URL when it is
saved and says in its own docstring that it cannot catch DNS rebinding,
because Next owns that fetcher. Here we own the fetcher, so the check happens
at connect time on the address actually connected to.

Three seams are monkeypatched by name and never exist as production knobs —
the module has no "allow private addresses" switch to find and flip:

- ``resolve_addresses`` — what DNS answered (patched on ``outbound``, whose
  own global binding is what the client calls).
- ``blocked_reason`` — the policy itself, relaxed only in the tests that are
  about something else (they delegate to the real function for every family
  but the one they need).
- ``_build_client`` — the httpx client, so a test can watch the request that
  would go out.
"""

from __future__ import annotations

import asyncio
import inspect
import socket
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from typing import Any

import httpx
import pytest
from yupay.core import outbound, outbound_addresses
from yupay.core.outbound import (
    AddressNotAllowedError,
    OutboundRefusedError,
    OutboundTimeoutError,
    ResolutionFailedError,
    ResponseTooLargeError,
    UrlNotAllowedError,
    post_json,
)

PUBLIC = "93.184.216.34"
SECOND_PUBLIC = "23.192.228.84"
URL = "https://webhook.example.test/hooks/yupay"

# ---------- stubs ----------


def _resolver(
    *answers: Sequence[str], calls: list[tuple[str, int]] | None = None
) -> Callable[[str, int], Any]:
    """A stub for ``_resolve_addresses`` answering each call in turn.

    The last answer repeats, so a single answer means "always this". Passing
    two answers is how a rebinding host is spelled: the first lookup returns
    one thing and every later lookup returns another.
    """
    queue = list(answers)

    async def _stub(host: str, port: int) -> tuple[str, ...]:
        if calls is not None:
            calls.append((host, port))
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        return tuple(answer)

    return _stub


_Handler = Callable[[httpx.Request], "httpx.Response | Awaitable[httpx.Response]"]


def _transport(handler: _Handler, seen: list[httpx.Request]) -> Callable[..., httpx.AsyncClient]:
    """A stub for ``_build_client`` recording every request the client sends.

    It builds the **real** client and replaces only its transport, rather
    than constructing a client of its own: every setting that makes the real
    one safe (``follow_redirects=False``, ``trust_env=False``, the timeouts)
    is then under test here too. A hand-rolled client would have quietly
    re-declared those, and flipping one in the module would leave these tests
    green — which it did, until this was written this way.
    """

    # Captured before the monkeypatch replaces the name, or the factory would
    # call itself.
    build = outbound._build_client

    async def _handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = handler(request)
        return await answer if inspect.isawaitable(answer) else answer

    def _factory(*, timeout: float) -> httpx.AsyncClient:
        client = build(timeout=timeout)
        client._transport = httpx.MockTransport(_handle)  # the socket, and only it
        return client

    return _factory


def _ok(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text="ok")


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    answers: Sequence[Sequence[str]] = ((PUBLIC,),),
    handler: _Handler = _ok,
    calls: list[tuple[str, int]] | None = None,
) -> list[httpx.Request]:
    """Stub DNS and the transport; return the list requests land in."""
    monkeypatch.setattr(outbound, "resolve_addresses", _resolver(*answers, calls=calls))
    seen: list[httpx.Request] = []
    monkeypatch.setattr(outbound, "_build_client", _transport(handler, seen))
    return seen


# ---------- property 1: https only, refused before anything is contacted ----------


@pytest.mark.parametrize(
    "url",
    [
        "http://webhook.example.test/hooks",
        "file:///etc/passwd",
        "gopher://webhook.example.test/",
        "ftp://webhook.example.test/",
        "ws://webhook.example.test/",
        "//webhook.example.test/hooks",
    ],
)
async def test_only_https_is_accepted(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    calls: list[tuple[str, int]] = []
    seen = _wire(monkeypatch, calls=calls)

    with pytest.raises(UrlNotAllowedError, match="https"):
        await post_json(url, body=b"{}")

    assert calls == [], "the scheme is refused before DNS is even asked"
    assert seen == [], "and before anything is connected to"


async def test_a_url_carrying_credentials_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []
    _wire(monkeypatch, calls=calls)

    with pytest.raises(UrlNotAllowedError, match="credentials"):
        await post_json("https://user:pw@webhook.example.test/hooks", body=b"{}")

    assert calls == []


async def test_a_url_without_a_host_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _wire(monkeypatch)

    with pytest.raises(UrlNotAllowedError, match="host"):
        await post_json("https:///hooks", body=b"{}")


async def test_the_refusal_message_never_carries_the_url_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A merchant's URL can carry a token in its query; a message is a log line."""
    _wire(monkeypatch)

    with pytest.raises(UrlNotAllowedError) as caught:
        await post_json("http://webhook.example.test/hooks?token=s3cr3t-in-the-query", body=b"{}")

    assert "s3cr3t-in-the-query" not in str(caught.value)


# ---------- property 3: every blocked family, by name ----------


async def _refused(monkeypatch: pytest.MonkeyPatch, address: str) -> AddressNotAllowedError:
    """Resolve the webhook host to ``address`` and return the refusal it raises."""
    seen = _wire(monkeypatch, answers=((address,),))
    with pytest.raises(AddressNotAllowedError) as caught:
        await post_json(URL, body=b"{}")
    assert seen == [], "a blocked address is never connected to"
    return caught.value


@pytest.mark.parametrize("address", ["127.0.0.1", "127.1.2.3", "::1", "::ffff:127.0.0.1"])
async def test_a_loopback_address_is_refused(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    assert "loopback" in str(await _refused(monkeypatch, address))


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1",  # RFC 1918 10/8
        "172.16.0.1",  # RFC 1918 172.16/12
        "172.31.255.254",  # ... its far end
        "192.168.1.1",  # RFC 1918 192.168/16
        "::ffff:10.0.0.1",
        "::ffff:172.16.0.1",
        "::ffff:192.168.1.1",
    ],
)
async def test_a_private_address_is_refused(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    assert "private" in str(await _refused(monkeypatch, address))


@pytest.mark.parametrize(
    "address",
    [
        "169.254.169.254",  # the cloud metadata endpoint, the whole point
        "169.254.0.1",
        "fe80::1",
        "::ffff:169.254.169.254",
    ],
)
async def test_a_link_local_address_is_refused(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    assert "link-local" in str(await _refused(monkeypatch, address))


@pytest.mark.parametrize("address", ["fc00::1", "fd12:3456:789a::1"])
async def test_a_unique_local_address_is_refused(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    assert "unique-local" in str(await _refused(monkeypatch, address))


@pytest.mark.parametrize("address", ["224.0.0.1", "239.255.255.250", "ff02::1", "::ffff:224.0.0.1"])
async def test_a_multicast_address_is_refused(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    assert "multicast" in str(await _refused(monkeypatch, address))


@pytest.mark.parametrize(
    "address",
    [
        "240.0.0.1",  # 240/4, reserved for future use
        "255.255.255.255",  # limited broadcast
        "64:ff9b::7f00:1",  # NAT64 with 127.0.0.1 embedded
        "::ffff:240.0.0.1",
    ],
)
async def test_a_reserved_address_is_refused(monkeypatch: pytest.MonkeyPatch, address: str) -> None:
    assert "reserved" in str(await _refused(monkeypatch, address))


@pytest.mark.parametrize("address", ["0.0.0.0", "0.1.2.3", "::ffff:0.0.0.0"])
async def test_the_this_network_block_is_refused(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    """``0.0.0.0/8`` — "this network". On Linux, 0.0.0.0 connects to localhost."""
    assert "this-network" in str(await _refused(monkeypatch, address))


async def test_the_unspecified_ipv6_address_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "unspecified" in str(await _refused(monkeypatch, "::"))


@pytest.mark.parametrize("address", ["100.64.0.1", "100.127.255.254"])
async def test_a_carrier_grade_nat_address_is_refused(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    """100.64/10 is neither private nor global — the catch-all is what stops it."""
    assert "not globally routable" in str(await _refused(monkeypatch, address))


@pytest.mark.parametrize("address", ["2002:7f00:1::", "2001:0:4136:e378:8000:63bf:3fff:fdd2"])
async def test_a_tunnelled_ipv6_address_is_refused(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    """6to4 and Teredo can carry an embedded IPv4 destination."""
    assert isinstance(await _refused(monkeypatch, address), AddressNotAllowedError)


async def test_a_scoped_ipv6_answer_keeps_its_family(monkeypatch: pytest.MonkeyPatch) -> None:
    """``ipaddress`` understands the ``%scope`` suffix, so the family still lands."""
    assert "link-local" in str(await _refused(monkeypatch, "fe80::1%eth0"))


@pytest.mark.parametrize("address", ["300.1.2.3", "", "not-an-address", "10.0.0.1 "])
async def test_an_answer_that_will_not_parse_is_refused(
    monkeypatch: pytest.MonkeyPatch, address: str
) -> None:
    """Fail closed on anything the policy cannot read, rather than skipping it."""
    assert "unreadable" in str(await _refused(monkeypatch, address))


@pytest.mark.parametrize("host", ["2130706433", "0x7f000001", "127.1"])
async def test_obfuscated_notation_is_resolved_rather_than_parsed(
    monkeypatch: pytest.MonkeyPatch, host: str
) -> None:
    """The real resolver runs here — this is what makes the client stronger.

    ``image_url_safety`` parses notation and says in its docstring that it
    does not normalise every obfuscation. This client never parses notation:
    it hands the host to the resolver and checks what comes back, so the
    bare-integer and hex spellings of 127.0.0.1 are refused as loopback
    without the policy knowing those spellings exist. No DNS query leaves the
    machine for any of these — the resolver answers them numerically.

    ``ResolutionFailedError`` is accepted as well because whether a libc
    resolves a given spelling is a platform detail; the claim under test is
    that none of them reaches a private address, and both outcomes hold it.
    """
    seen: list[httpx.Request] = []
    monkeypatch.setattr(outbound, "_build_client", _transport(_ok, seen))

    with pytest.raises((AddressNotAllowedError, ResolutionFailedError)) as caught:
        await post_json(f"https://{host}/hooks", body=b"{}")

    if isinstance(caught.value, AddressNotAllowedError):
        assert "loopback" in str(caught.value)
    assert seen == []


# ---------- property 2: every answer must be public, and the pin is honoured ----------


async def test_one_private_answer_beside_a_public_one_refuses_the_whole_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a race to pick the good one — a mixed answer is refused outright."""
    seen = _wire(monkeypatch, answers=((PUBLIC, "127.0.0.1"),))

    with pytest.raises(AddressNotAllowedError) as caught:
        await post_json(URL, body=b"{}")

    assert "127.0.0.1" in str(caught.value)
    assert seen == []


async def test_a_private_answer_listed_first_refuses_the_whole_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch, answers=(("10.0.0.5", PUBLIC),))

    with pytest.raises(AddressNotAllowedError):
        await post_json(URL, body=b"{}")

    assert seen == []


async def test_the_request_goes_to_the_checked_address_not_the_hostname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch, answers=((PUBLIC, SECOND_PUBLIC),))

    result = await post_json(URL, body=b'{"a":1}')

    assert result.status_code == 200
    assert result.address == PUBLIC
    request = seen[0]
    assert request.url.host == PUBLIC, "the URL carries the pinned address, not the name"
    assert request.headers["host"] == "webhook.example.test"
    assert request.extensions["sni_hostname"] == "webhook.example.test"
    assert request.url.path == "/hooks/yupay"
    assert request.content == b'{"a":1}'


async def test_a_second_lookup_that_would_answer_differently_is_never_made(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rebinding case, hermetically: lookup 1 is public, lookup 2 is loopback.

    One resolution happens and the connection uses its answer. If the client
    connected by name, the socket layer's own lookup would be the second one
    and would land on 127.0.0.1 — which is the bug this module exists to
    prevent. The live suite proves the same thing against real sockets.
    """
    calls: list[tuple[str, int]] = []
    seen = _wire(monkeypatch, answers=((PUBLIC,), ("127.0.0.1",)), calls=calls)

    result = await post_json(URL, body=b"{}")

    assert calls == [("webhook.example.test", 443)], "resolved once, not once per layer"
    assert result.address == PUBLIC
    assert seen[0].url.host == PUBLIC


async def test_a_non_default_port_is_kept_on_both_the_socket_and_the_host_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch)

    await post_json("https://webhook.example.test:8443/hooks", body=b"{}")

    assert seen[0].url.port == 8443
    assert seen[0].headers["host"] == "webhook.example.test:8443"


async def test_an_ipv6_literal_in_the_url_keeps_its_brackets_in_the_host_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch, answers=(("2606:4700:4700::1111",),))

    await post_json("https://[2606:4700:4700::1111]/hooks", body=b"{}")

    assert seen[0].headers["host"] == "[2606:4700:4700::1111]"


async def test_an_ipv6_answer_is_pinned_with_brackets(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _wire(monkeypatch, answers=(("2606:4700:4700::1111",),))

    result = await post_json(URL, body=b"{}")

    assert result.address == "2606:4700:4700::1111"
    assert seen[0].url.host == "2606:4700:4700::1111"


async def test_the_guard_refuses_a_socket_target_that_is_not_the_pinned_address() -> None:
    """The last line of defence, tested directly.

    ``_connect_guard`` watches httpcore's ``connect_tcp`` trace and refuses
    the moment the host handed to the socket layer is not the address the
    policy cleared. It is what turns "we build the URL from the pinned
    address" from a convention into an enforced invariant, so a future edit
    that reintroduces connect-by-name fails closed instead of silently
    re-opening the hole.
    """
    guard = outbound._connect_guard(pinned=PUBLIC, host="webhook.example.test")

    await guard("connection.connect_tcp.started", {"host": PUBLIC, "port": 443})

    with pytest.raises(AddressNotAllowedError, match="socket"):
        await guard("connection.connect_tcp.started", {"host": "webhook.example.test", "port": 443})


async def test_the_client_ignores_proxy_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A proxy would connect by name on our behalf and void the whole check."""
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:3128")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:1080")

    client = outbound._build_client(timeout=1.0)
    try:
        assert client.trust_env is False
        assert client._mounts == {}
    finally:
        await client.aclose()


# ---------- property 4: a 30x is an outcome, not a hop ----------


async def test_a_redirect_is_returned_as_a_result_and_never_followed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _redirect(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://169.254.169.254/latest/meta-data/"},
            text="moved",
        )

    seen = _wire(monkeypatch, handler=_redirect)

    result = await post_json(URL, body=b"{}")

    assert result.status_code == 302
    assert len(seen) == 1, "the Location target is never fetched"
    assert seen[0].url.host == PUBLIC


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
async def test_every_redirect_status_is_an_outcome(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    seen = _wire(
        monkeypatch,
        handler=lambda _r: httpx.Response(status, headers={"location": "https://elsewhere.test/"}),
    )

    result = await post_json(URL, body=b"{}")

    assert result.status_code == status
    assert len(seen) == 1


# ---------- property 5: size and time are both capped ----------


async def test_a_response_over_the_byte_cap_is_a_typed_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch, handler=lambda _r: httpx.Response(200, content=b"x" * 5000))

    with pytest.raises(ResponseTooLargeError, match="1024"):
        await post_json(URL, body=b"{}", max_bytes=1024)

    assert len(seen) == 1


async def test_a_streaming_body_is_cut_off_rather_than_read_to_the_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cap stops the read; it does not buffer everything and measure after."""
    chunks_yielded = 0

    async def _endless() -> AsyncIterator[bytes]:
        nonlocal chunks_yielded
        while True:
            chunks_yielded += 1
            yield b"x" * 1024

    _wire(monkeypatch, handler=lambda _r: httpx.Response(200, content=_endless()))

    with pytest.raises(ResponseTooLargeError):
        await post_json(URL, body=b"{}", max_bytes=4096)

    assert chunks_yielded <= 6, "stopped at the cap, not at the end of the stream"


async def test_a_response_at_the_cap_exactly_is_still_a_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, handler=lambda _r: httpx.Response(200, content=b"x" * 1024))

    result = await post_json(URL, body=b"{}", max_bytes=1024)

    assert result.status_code == 200
    assert len(result.body) == 1024


async def test_a_slow_server_is_a_typed_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _slow(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    _wire(monkeypatch, handler=_slow)

    with pytest.raises(OutboundTimeoutError):
        await post_json(URL, body=b"{}", timeout=0.05)


async def test_a_body_that_drips_forever_hits_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A per-read timeout would never fire here; the total deadline must."""

    async def _drip() -> AsyncIterator[bytes]:
        while True:
            await asyncio.sleep(0.01)
            yield b"x"

    _wire(monkeypatch, handler=lambda _r: httpx.Response(200, content=_drip()))

    with pytest.raises(OutboundTimeoutError):
        await post_json(URL, body=b"{}", timeout=0.2, max_bytes=1_000_000)


async def test_a_transport_failure_is_unreachable_not_a_policy_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 4 records "we refused" and "they did not answer" differently."""

    def _boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    _wire(monkeypatch, handler=_boom)

    with pytest.raises(outbound.ConnectFailedError) as caught:
        await post_json(URL, body=b"{}")

    assert not isinstance(caught.value, OutboundRefusedError)
    assert isinstance(caught.value, outbound.OutboundUnreachableError)


async def test_dns_failure_is_unreachable_not_a_policy_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _nxdomain(host: str, port: int) -> list[Any]:
        raise socket.gaierror(-2, "Name or service not known")

    monkeypatch.setattr(outbound_addresses, "_getaddrinfo", _nxdomain)

    with pytest.raises(ResolutionFailedError) as caught:
        await post_json(URL, body=b"{}")

    assert not isinstance(caught.value, OutboundRefusedError)


async def test_an_empty_dns_answer_is_a_resolution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, answers=((),))

    with pytest.raises(ResolutionFailedError):
        await post_json(URL, body=b"{}")


# ---------- property 6: nothing we send is ever logged ----------


class _Recorder:
    """Stands in for the module logger, keeping everything it was handed.

    Not ``structlog.testing.capture_logs``: ``configure_logging`` sets
    ``cache_logger_on_first_use``, so a module-level logger bound earlier in
    the session keeps its old processor chain and the capture comes back
    empty (the same trap ``test_metrics_labels`` documents).
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _record(self, event: str, **fields: Any) -> None:
        self.calls.append(f"{event} {fields!r}")

    debug = info = warning = error = exception = _record


async def test_nothing_the_client_sends_is_ever_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(outbound, "log", recorder)
    _wire(monkeypatch, handler=lambda _r: httpx.Response(200, text="thanks"))

    await post_json(
        "https://webhook.example.test/hooks?token=query-s3cr3t",
        body=b'{"order_id":"o-1","code":"body-s3cr3t"}',
        headers={"X-Yupay-Signature": "sig-s3cr3t", "Authorization": "Bearer header-s3cr3t"},
    )

    logged = "\n".join(recorder.calls)
    assert logged, "the delivery attempt is logged at all"
    for secret in ("body-s3cr3t", "sig-s3cr3t", "header-s3cr3t", "query-s3cr3t"):
        assert secret not in logged


async def test_a_refusal_is_logged_without_the_body_either(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    monkeypatch.setattr(outbound, "log", recorder)
    _wire(monkeypatch, answers=(("169.254.169.254",),))

    with pytest.raises(AddressNotAllowedError):
        await post_json(URL, body=b'{"code":"body-s3cr3t"}', headers={"X-S": "sig-s3cr3t"})

    logged = "\n".join(recorder.calls)
    assert "body-s3cr3t" not in logged
    assert "sig-s3cr3t" not in logged


async def test_our_headers_go_to_the_pinned_host_and_nowhere_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Property 6's other half: with no redirect followed, there is no second hop."""
    seen = _wire(
        monkeypatch,
        handler=lambda _r: httpx.Response(302, headers={"location": "https://attacker.test/"}),
    )

    await post_json(URL, body=b"{}", headers={"X-Yupay-Signature": "sig"})

    assert [r.url.host for r in seen] == [PUBLIC]
    assert seen[0].headers["x-yupay-signature"] == "sig"


async def test_the_caller_cannot_override_the_pinned_host_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _wire(monkeypatch)

    await post_json(URL, body=b"{}", headers={"Host": "somewhere.else.test"})

    assert seen[0].headers["host"] == "webhook.example.test"


# ---------- the result the caller records ----------


async def test_the_result_carries_what_the_delivery_log_needs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, handler=lambda _r: httpx.Response(503, text="try later"))

    result = await post_json(URL, body=b"{}")

    assert result.status_code == 503
    assert result.body == "try later"
    assert result.address == PUBLIC
    assert result.elapsed_ms >= 0


async def test_a_body_that_is_not_utf8_still_comes_back_as_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The log is for a human to read; undecodable bytes must not raise."""
    _wire(monkeypatch, handler=lambda _r: httpx.Response(200, content=b"\xff\xfe not utf8"))

    result = await post_json(URL, body=b"{}")

    assert "not utf8" in result.body
