"""Live-socket tests for the SSRF-safe outbound client (M3a, Task 2).

Real listeners on real loopback ports. The unit suite
(``tests/unit/test_outbound_ssrf.py``) proves the policy against a stubbed
transport; this file proves the two things a stub cannot:

1. **A server that is really there is really not contacted.** Every refusal
   test points the client at a socket that is accepting connections and
   asserts the accept count stayed at zero. A policy that refuses *after*
   connecting would pass a mock-transport test and fail these.
2. **The connection lands on the address the policy checked.** Two listeners
   on the same port at different loopback addresses, and a resolver that
   answers the first address once and the second address ever after — the
   DNS-rebinding shape, with sockets. The request must arrive at the first
   and the second must never see an accept.

Nothing here reaches the network: the only addresses used are loopback ones,
and the hostname is a ``.test`` name that is never resolved (the resolver is
stubbed for it). TLS is real, against a throwaway certificate minted per
test, which is also how the SNI assertion is possible — the client presents
the *hostname* while connecting to the *address*.

Two seams are monkeypatched, both private module functions rather than
production switches: ``blocked_reason`` (relaxed for loopback only, in the
tests that are not about the policy) and ``_ssl_context`` (to trust the
throwaway CA). ``resolve_addresses`` stands in for DNS.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import gzip
import ipaddress
import socket
import ssl
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from yupay.core import outbound, outbound_addresses
from yupay.core.outbound import (
    AddressNotAllowedError,
    ConnectFailedError,
    ContentEncodingNotAllowedError,
    Delivery,
    OutboundTimeoutError,
    ResponseTooLargeError,
    UrlNotAllowedError,
    post_json,
)

pytestmark = pytest.mark.asyncio

HOSTNAME = "webhook.example.test"

Responder = Callable[[asyncio.StreamWriter], Awaitable[None]]


# ---------- a throwaway certificate for the hostname ----------


@pytest.fixture(scope="module")
def _certificate(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A self-signed cert for ``HOSTNAME``, trusted only by these tests."""
    directory = tmp_path_factory.mktemp("outbound-tls")
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOSTNAME)])
    now = dt.datetime.now(tz=dt.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(hours=1))
        .not_valid_after(now + dt.timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(HOSTNAME)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path = directory / "cert.pem"
    key_path = directory / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.fixture
def trusting_client(monkeypatch: pytest.MonkeyPatch, _certificate: tuple[Path, Path]) -> None:
    """Point the client's TLS verification at the throwaway CA."""
    cert_path, _ = _certificate
    context = ssl.create_default_context(cafile=str(cert_path))
    monkeypatch.setattr(outbound, "_ssl_context", lambda: context)


@pytest.fixture
def loopback_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let loopback through the policy — and nothing else.

    The tests that use this are about redirects, caps, timeouts and pinning,
    not about the policy: they need a listener the client will actually talk
    to, and loopback is the only address a test can bind. Every other family
    still goes through the real :func:`_blocked_reason`, and the tests that
    are about the policy do not use this fixture.
    """
    # Captured from its home module and patched on the client's binding —
    # ``outbound`` imports the name, and that binding is what it calls.
    real = outbound_addresses.blocked_reason

    def _patched(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
        reason = real(ip)
        return None if reason == "loopback" else reason

    monkeypatch.setattr(outbound, "blocked_reason", _patched)


def _addrinfo(address: str, port: int) -> tuple[object, ...]:
    """One ``getaddrinfo`` 5-tuple for ``address``."""
    if ":" in address:
        return (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port, 0, 0))
    return (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port))


def _system_resolver_answers(monkeypatch: pytest.MonkeyPatch, *answers: Sequence[str]) -> list[str]:
    """Stub the **system** resolver — the one both halves of the client reach.

    ``socket.getaddrinfo`` is what ``loop.getaddrinfo`` runs, which is what
    our own resolution *and* anyio's ``connect_tcp`` both end up calling. That
    is what makes a rebinding test real: patching our own function instead
    leaves the socket layer answering from the real resolver, so the "second
    answer" could never have been reached however the client was written, and
    the assertion about it could never fail.

    Only ``HOSTNAME`` is answered from the queue; everything else — the
    pinned literal included — is delegated, because a literal must resolve to
    itself for the connection to happen at all.
    """
    real = socket.getaddrinfo
    queue = list(answers)
    asked: list[str] = []

    def _stub(host: object, port: object, *args: object, **kwargs: object) -> list[object]:
        # anyio hands the socket layer's lookup an **ASCII-encoded** host, so
        # comparing against the str form alone silently delegates the very
        # lookup this stub exists to answer.
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name != HOSTNAME:
            return list(real(host, port, *args, **kwargs))  # type: ignore[arg-type]
        asked.append(name)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        return [_addrinfo(address, int(str(port))) for address in answer]

    monkeypatch.setattr(socket, "getaddrinfo", _stub)
    return asked


def _resolves_to(monkeypatch: pytest.MonkeyPatch, *answers: Sequence[str]) -> list[str]:
    """Stub DNS with one answer per call (the last repeats); return the call log."""
    queue = list(answers)
    calls: list[str] = []

    async def _stub(host: str, port: int) -> tuple[str, ...]:
        calls.append(host)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        return tuple(answer)

    monkeypatch.setattr(outbound, "resolve_addresses", _stub)
    return calls


# ---------- listeners ----------


class _Probe:
    """A plain TCP listener that only counts accepts.

    Deliberately not TLS: an accept is recorded the instant a TCP connection
    lands, before any handshake could fail, so "this socket was never
    contacted" means exactly that.
    """

    def __init__(self) -> None:
        self.accepts = 0
        self._server: asyncio.Server | None = None

    async def start(self, address: str, port: int = 0) -> int:
        async def _handle(_r: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            self.accepts += 1
            writer.close()

        self._server = await asyncio.start_server(_handle, address, port)
        return int(self._server.sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(0.5):
                    await self._server.wait_closed()


class _TlsServer:
    """A minimal HTTPS/1.1 listener that records what it was sent."""

    def __init__(self, certificate: tuple[Path, Path], responder: Responder) -> None:
        cert_path, key_path = certificate
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert_path), str(key_path))
        context.set_alpn_protocols(["http/1.1"])
        context.sni_callback = self._record_sni
        self._context = context
        self._responder = responder
        self._server: asyncio.Server | None = None
        self.sni_names: list[str | None] = []
        self.requests: list[tuple[bytes, bytes]] = []

    def _record_sni(self, _sock: ssl.SSLObject, name: str | None, _ctx: ssl.SSLContext) -> None:
        self.sni_names.append(name)

    @property
    def handshakes(self) -> int:
        return len(self.sni_names)

    async def start(self, address: str, port: int = 0) -> int:
        self._server = await asyncio.start_server(self._handle, address, port, ssl=self._context)
        return int(self._server.sockets[0].getsockname()[1])

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
            length = 0
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-length:"):
                    length = int(line.split(b":", 1)[1])
            body = await reader.readexactly(length) if length else b""
            self.requests.append((head, body))
            await self._responder(writer)
        except (
            TimeoutError,
            asyncio.IncompleteReadError,
            ConnectionError,
            ssl.SSLError,
        ):  # pragma: no cover -- the client hung up first, which several tests do
            pass
        finally:
            with contextlib.suppress(ConnectionError, ssl.SSLError):
                writer.close()

    async def stop(self) -> None:
        # ``wait_closed`` waits for open handlers too (3.12 changed that), and
        # one test's responder deliberately never answers — so bound the wait
        # instead of hanging the suite on it.
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(TimeoutError, ConnectionError, ssl.SSLError):
                async with asyncio.timeout(0.5):
                    await self._server.wait_closed()


def _respond(status: str, body: bytes, extra: str = "") -> Responder:
    """A responder that writes one fixed HTTP/1.1 response."""

    async def _write(writer: asyncio.StreamWriter) -> None:
        head = (
            f"HTTP/1.1 {status}\r\n{extra}Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        )
        writer.write(head.encode() + body)
        await writer.drain()

    return _write


def _respond_with_a_flood(total: int) -> Responder:
    """A responder that streams ``total`` bytes in 8 KiB chunks."""

    async def _write(writer: asyncio.StreamWriter) -> None:
        head = f"HTTP/1.1 200 OK\r\nContent-Length: {total}\r\nConnection: close\r\n\r\n"
        writer.write(head.encode())
        written = 0
        while written < total:
            chunk = b"x" * min(8192, total - written)
            writer.write(chunk)
            written += len(chunk)
            await writer.drain()

    return _write


async def _never_answer(_writer: asyncio.StreamWriter) -> None:
    """Accept the request, read it, and then simply never reply."""
    await asyncio.sleep(30)


@contextlib.asynccontextmanager
async def _serving(
    certificate: tuple[Path, Path], responder: Responder, address: str = "127.0.0.1"
) -> AsyncIterator[tuple[_TlsServer, int]]:
    server = _TlsServer(certificate, responder)
    port = await server.start(address)
    try:
        yield server, port
    finally:
        await server.stop()


def _second_loopback() -> str:
    """A loopback address that is not ``127.0.0.1``, or skip.

    ``::1`` everywhere that has IPv6, ``127.0.0.2`` on Linux where all of
    127/8 is local. The pinning test needs two distinct addresses on one
    port, and these are the only two an unprivileged test can bind.
    """
    for candidate in ("::1", "127.0.0.2"):
        family = socket.AF_INET6 if ":" in candidate else socket.AF_INET
        with socket.socket(family, socket.SOCK_STREAM) as probe_socket:
            try:
                probe_socket.bind((candidate, 0))
            except OSError:
                continue
            return candidate
    pytest.skip("no second loopback address available to bind")


# ---------- the refusals, against sockets that are really listening ----------


async def test_a_loopback_server_behind_a_public_looking_hostname_is_never_contacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = _Probe()
    port = await listener.start("127.0.0.1")
    try:
        _resolves_to(monkeypatch, ("127.0.0.1",))

        with pytest.raises(AddressNotAllowedError, match="loopback"):
            await post_json(f"https://{HOSTNAME}:{port}/hooks", body=b"{}")

        await asyncio.sleep(0.05)
        assert listener.accepts == 0
    finally:
        await listener.stop()


async def test_a_plain_http_url_never_reaches_the_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    listener = _Probe()
    port = await listener.start("127.0.0.1")
    try:
        _resolves_to(monkeypatch, ("127.0.0.1",))

        with pytest.raises(UrlNotAllowedError, match="https"):
            await post_json(f"http://{HOSTNAME}:{port}/hooks", body=b"{}")

        await asyncio.sleep(0.05)
        assert listener.accepts == 0
    finally:
        await listener.stop()


# ---------- the pin ----------


async def test_the_connection_lands_on_the_address_the_policy_checked(
    monkeypatch: pytest.MonkeyPatch,
    _certificate: tuple[Path, Path],
    trusting_client: None,
    loopback_allowed: None,
) -> None:
    """DNS rebinding, with sockets, against the resolver the socket layer uses.

    The host answers ``127.0.0.1`` once and the other loopback address ever
    after, with a second listener waiting there on the same port. A client
    that resolved and then connected **by name** would hand the hostname to
    the socket layer, whose own lookup is the second one, and the request
    would arrive at the wrong listener — which is the whole bug. It must
    arrive at the first, and the second must never see an accept.

    The stub is on ``socket.getaddrinfo`` rather than on our own resolver
    precisely so that assertion can fail: with our function stubbed, the
    second answer is unreachable from the socket layer no matter what the
    client does.
    """
    other = _second_loopback()
    async with _serving(_certificate, _respond("200 OK", b"delivered")) as (server, port):
        # A second **TLS** server, not a bare probe, and holding the same
        # certificate: a client that connected by name would complete the
        # exchange here and come back with a 200 the assertions can catch. A
        # probe would only break the handshake, and the test would pass on the
        # exception rather than on the address.
        rebound = _TlsServer(_certificate, _respond("200 OK", b"wrong-listener"))
        await rebound.start(other, port)
        try:
            asked = _system_resolver_answers(monkeypatch, ("127.0.0.1",), (other,))

            result = await post_json(f"https://{HOSTNAME}:{port}/hooks", body=b'{"id":1}')

            assert result.body == "delivered", "answered by the address the policy checked"
            assert result.status_code == 200
            assert result.address == "127.0.0.1"
            assert len(server.requests) == 1
            await asyncio.sleep(0.05)
            assert rebound.handshakes == 0, "the second answer was never connected to"
            assert rebound.requests == []
            assert asked == [HOSTNAME], "the name was resolved once, not once per layer"
        finally:
            await rebound.stop()


async def test_connecting_by_name_instead_of_the_pin_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    _certificate: tuple[Path, Path],
    trusting_client: None,
    loopback_allowed: None,
) -> None:
    """The falsification test for this whole module.

    ``_pinned_url`` is sabotaged into the exact bug the task exists to
    prevent — build the request against the *hostname* after checking the
    address — and the connect-time guard must catch it. ``localhost`` is used
    because it really does resolve, so without the guard the request would
    land on the listener below.
    """
    async with _serving(_certificate, _respond("200 OK", b"delivered")) as (server, port):
        _resolves_to(monkeypatch, ("127.0.0.1",))
        monkeypatch.setattr(
            outbound,
            "_pinned_url",
            lambda target, address: f"https://localhost:{target.port}{target.path}",
        )

        with pytest.raises(AddressNotAllowedError, match="socket"):
            await post_json(f"https://{HOSTNAME}:{port}/hooks", body=b"{}")

        await asyncio.sleep(0.05)
        assert server.handshakes == 0, "refused before the socket was opened"


# ---------- the delivery itself ----------


async def test_a_delivery_presents_the_hostname_and_returns_what_the_log_needs(
    monkeypatch: pytest.MonkeyPatch,
    _certificate: tuple[Path, Path],
    trusting_client: None,
    loopback_allowed: None,
) -> None:
    async with _serving(_certificate, _respond("200 OK", b"thanks")) as (server, port):
        _resolves_to(monkeypatch, ("127.0.0.1",))

        result = await post_json(
            f"https://{HOSTNAME}:{port}/hooks/yupay",
            body=b'{"event":"order.status_changed"}',
            headers={"X-Yupay-Signature": "t=1,v1=deadbeef"},
        )

        assert result.status_code == 200
        assert result.body == "thanks"
        assert result.address == "127.0.0.1"
        assert result.elapsed_ms >= 0

        head, body = server.requests[0]
        assert head.startswith(b"POST /hooks/yupay HTTP/1.1\r\n")
        assert f"host: {HOSTNAME}:{port}".encode() in head.lower()
        assert b"x-yupay-signature: t=1,v1=deadbeef" in head.lower()
        assert body == b'{"event":"order.status_changed"}'
        assert server.sni_names == [HOSTNAME], "TLS was negotiated for the name, not the address"


async def test_a_redirect_to_the_metadata_address_is_an_outcome_not_a_hop(
    monkeypatch: pytest.MonkeyPatch,
    _certificate: tuple[Path, Path],
    trusting_client: None,
    loopback_allowed: None,
) -> None:
    responder = _respond(
        "302 Found", b"", extra="Location: http://169.254.169.254/latest/meta-data/\r\n"
    )
    async with _serving(_certificate, responder) as (server, port):
        _resolves_to(monkeypatch, ("127.0.0.1",))

        result = await post_json(f"https://{HOSTNAME}:{port}/hooks", body=b"{}")

        assert result.status_code == 302
        assert len(server.requests) == 1


async def test_a_response_bigger_than_the_cap_is_refused(
    monkeypatch: pytest.MonkeyPatch,
    _certificate: tuple[Path, Path],
    trusting_client: None,
    loopback_allowed: None,
) -> None:
    async with _serving(_certificate, _respond_with_a_flood(512 * 1024)) as (_server, port):
        _resolves_to(monkeypatch, ("127.0.0.1",))

        with pytest.raises(ResponseTooLargeError):
            await post_json(f"https://{HOSTNAME}:{port}/hooks", body=b"{}", max_bytes=8192)


async def test_a_compressed_answer_is_refused_off_a_real_socket(
    monkeypatch: pytest.MonkeyPatch,
    _certificate: tuple[Path, Path],
    trusting_client: None,
    loopback_allowed: None,
) -> None:
    """We asked for identity; this server compresses anyway, as they can.

    20 MB of zeros leaves the socket as a few KB. Reading it through httpx's
    decoder would expand it in this process before any cap could see it, so
    the response is refused on its ``Content-Encoding`` before a byte of the
    body is read — and it counts as delivered, because it plainly was.
    """
    bomb = gzip.compress(b"\0" * 20_000_000)
    responder = _respond("200 OK", bomb, extra="Content-Encoding: gzip\r\n")
    async with _serving(_certificate, responder) as (server, port):
        _resolves_to(monkeypatch, ("127.0.0.1",))

        with pytest.raises(ContentEncodingNotAllowedError) as caught:
            await post_json(f"https://{HOSTNAME}:{port}/hooks", body=b"{}")

        assert caught.value.delivery is Delivery.RECEIVED
        assert len(server.requests) == 1, "they received the webhook; only the answer is refused"


async def test_a_server_that_never_answers_hits_the_deadline(
    monkeypatch: pytest.MonkeyPatch,
    _certificate: tuple[Path, Path],
    trusting_client: None,
    loopback_allowed: None,
) -> None:
    async with _serving(_certificate, _never_answer) as (server, port):
        _resolves_to(monkeypatch, ("127.0.0.1",))

        with pytest.raises(OutboundTimeoutError):
            await post_json(f"https://{HOSTNAME}:{port}/hooks", body=b"{}", timeout=0.5)

        assert len(server.requests) == 1, "they got the delivery; they just never answered"


async def test_a_closed_port_is_unreachable_rather_than_refused(
    monkeypatch: pytest.MonkeyPatch,
    trusting_client: None,
    loopback_allowed: None,
) -> None:
    """The other half of ruling 5: nobody is listening is not a policy refusal."""
    listener = _Probe()
    port = await listener.start("127.0.0.1")
    await listener.stop()
    _resolves_to(monkeypatch, ("127.0.0.1",))

    with pytest.raises(ConnectFailedError):
        await post_json(f"https://{HOSTNAME}:{port}/hooks", body=b"{}", timeout=2.0)
