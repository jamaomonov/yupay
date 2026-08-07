"""The address every guard and the evidence capture key on."""

from __future__ import annotations

from typing import Any

from starlette.datastructures import Headers
from yupay.core.client_ip import UNKNOWN_IP, client_ip


class _Req:
    """Stand-in for the two attributes ``client_ip`` reads.

    Uses Starlette's own ``Headers`` rather than a dict so the case-insensitive
    lookup under test is the real one — a dict here would make the test pass or
    fail on the stub's behaviour instead of the app's.
    """

    def __init__(self, headers: dict[str, str], peer: str | None) -> None:
        self.headers = Headers(headers)
        self.client = type("C", (), {"host": peer})() if peer else None


def _req(headers: dict[str, str] | None = None, peer: str | None = None) -> Any:
    return _Req(headers or {}, peer)


def test_takes_the_first_forwarded_entry() -> None:
    # The edge overwrites the header with the real peer and our own Caddy then
    # appends itself, so the client is the leftmost entry — never the last.
    assert (
        client_ip(_req({"X-Forwarded-For": "203.0.113.7, 10.0.0.2"}, "10.0.0.2")) == "203.0.113.7"
    )


def test_header_lookup_is_case_insensitive() -> None:
    # Starlette headers are case-insensitive; asserting it so a refactor to
    # plain dicts cannot silently start missing the header in production.
    assert client_ip(_req({"x-forwarded-for": "198.51.100.4"}, "10.0.0.2")) == "198.51.100.4"


def test_falls_back_to_the_socket_peer() -> None:
    assert client_ip(_req({}, "192.0.2.9")) == "192.0.2.9"


def test_empty_header_does_not_shadow_the_peer() -> None:
    # A blank or comma-only header would otherwise yield "", which downstream
    # would happily store as an address and key a rate-limit bucket on.
    assert client_ip(_req({"X-Forwarded-For": "   "}, "192.0.2.9")) == "192.0.2.9"
    assert client_ip(_req({"X-Forwarded-For": ","}, "192.0.2.9")) == "192.0.2.9"


def test_reports_unknown_when_there_is_no_peer_at_all() -> None:
    assert client_ip(_req({}, None)) == UNKNOWN_IP
