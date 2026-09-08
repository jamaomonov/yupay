"""Which resolved addresses this deployment will open a connection to.

Split out of :mod:`yupay.core.outbound` so the question "is this address one
we may talk to" can be read, reviewed and tested without any HTTP around it —
and so neither half grows past AGENTS.md §6's file limit. The client owns the
refusing; this module only classifies and resolves, and raises nothing of its
own.

Every function here works on a **resolved address**, never a hostname and
never notation, which is what lets it make the check
:mod:`yupay.modules.catalog.image_url_safety` documents itself as unable to
make: the obfuscated spellings of ``127.0.0.1`` it lists as out of scope
(``2130706433``, ``0x7f000001``) are the resolver's problem, and by the time
an address reaches :func:`blocked_reason` they have been normalised away.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Callable
from typing import Final

_THIS_NETWORK_V4: Final = ipaddress.IPv4Network("0.0.0.0/8")
_UNIQUE_LOCAL_V6: Final = ipaddress.IPv6Network("fc00::/7")

_AddrInfo = tuple[
    socket.AddressFamily,
    socket.SocketKind,
    int,
    str,
    tuple[str, int] | tuple[str, int, int, int],
]

#: Either address type, as one name — the policy treats them alike.
IpAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _embedded_ipv4(ip: IpAddress) -> ipaddress.IPv4Address | None:
    """The IPv4 address tunnelled inside an IPv6 one, if there is one.

    ``::ffff:127.0.0.1`` (IPv4-mapped), ``2002:7f00:1::`` (6to4) and Teredo
    all carry an IPv4 destination that the IPv6 checks alone would not
    classify. The mapped form is the one an attacker reaches for first.
    """
    if not isinstance(ip, ipaddress.IPv6Address):
        return None
    if ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    if ip.sixtofour is not None:
        return ip.sixtofour
    if ip.teredo is not None:
        return ip.teredo[1]
    return None


#: The blocked families, in the order their names are tried. This is the one
#: range table in the repo: :mod:`yupay.modules.catalog.image_url_safety`
#: classifies its save-time IP literals through :func:`blocked_reason` rather
#: than keeping a second list. Sharing the *table* is what M3a Task 2's ruling
#: 4 asks for; sharing the entry point is what it forbids, and the two callers
#: still differ in what they are handed (notation there, resolved addresses
#: here).
#:
#: Order decides which name a multi-family address reports, so the specific
#: ones come first: ``240.0.0.1`` is both reserved and (to Python) private, and
#: "reserved" is the half worth reading in a delivery log. Every entry is a
#: family the spec names; the ``is_global`` catch-all after this table is
#: what stops the ones with no name here, such as carrier-grade NAT
#: (``100.64.0.0/10``), which is neither private nor reserved.
BLOCKED_FAMILIES: Final[tuple[tuple[str, Callable[[IpAddress], bool]], ...]] = (
    ("loopback", lambda ip: ip.is_loopback),
    ("link-local", lambda ip: ip.is_link_local),
    ("unique-local", lambda ip: isinstance(ip, ipaddress.IPv6Address) and ip in _UNIQUE_LOCAL_V6),
    # RFC 3879 site-local. It needs its own entry because Python excludes
    # ``fec0::/10`` from BOTH ``is_private`` and ``is_global`` — deprecated in
    # 2004, still routed inside plenty of estates, and it would otherwise fall
    # through this table AND the ``is_global`` catch-all under it.
    ("site-local", lambda ip: isinstance(ip, ipaddress.IPv6Address) and ip.is_site_local),
    ("multicast", lambda ip: ip.is_multicast),
    ("this-network", lambda ip: isinstance(ip, ipaddress.IPv4Address) and ip in _THIS_NETWORK_V4),
    ("unspecified", lambda ip: ip.is_unspecified),
    ("reserved", lambda ip: ip.is_reserved),
    ("private", lambda ip: ip.is_private),
)


def blocked_reason(ip: IpAddress) -> str | None:
    """Name the family that bars this address, or ``None`` if it is public.

    The families and their order are :data:`BLOCKED_FAMILIES`; anything they
    miss is caught by ``is_global`` below them.

    Args:
        ip: A resolved address, never a hostname and never notation.

    Returns:
        A short family name for a blocked address, else ``None``.
    """
    embedded = _embedded_ipv4(ip)
    if embedded is not None:
        embedded_reason = blocked_reason(embedded)
        if embedded_reason is not None:
            return f"{embedded_reason} (tunnelled in an IPv6 address)"
    for family, matches in BLOCKED_FAMILIES:
        if matches(ip):
            return family
    return None if ip.is_global else "not globally routable"


async def _getaddrinfo(host: str, port: int) -> list[_AddrInfo]:
    """``loop.getaddrinfo``, isolated so the tests can stand in for DNS.

    ``AI_ADDRCONFIG`` matters here in a way it would not for an ordinary
    client: the caller pins the **first** answer and does not fall back to the
    rest, so on an IPv4-only host (which is what a default Docker network is)
    an unfiltered lookup of a dual-stack merchant would hand back their AAAA
    record, pin it, and fail every delivery. The flag asks the resolver for
    families this host actually has configured, which is the same thing a
    connect-by-name would have got.
    """
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(
        host,
        port,
        type=socket.SOCK_STREAM,
        proto=socket.IPPROTO_TCP,
        flags=socket.AI_ADDRCONFIG,
    )


async def resolve_addresses(host: str, port: int) -> tuple[str, ...]:
    """Resolve ``host`` once, preserving the resolver's ordering.

    Once, and by us: a caller that resolved here and then connected by name
    would let the socket layer resolve a second time, and the second answer
    can differ from the one that was checked.

    Args:
        host: The hostname (or IP literal) from the URL.
        port: The destination port, which getaddrinfo wants for the service.

    Returns:
        Every distinct address the resolver returned, in its order — the
        first is the one RFC 6724 says to prefer, and the one the client pins.

    Raises:
        OSError: The lookup failed. The caller turns it into its own typed
            "they could not be reached" error; this module raises nothing of
            its own.
    """
    infos = await _getaddrinfo(host, port)
    return tuple(dict.fromkeys(str(info[4][0]) for info in infos))


__all__ = ["BLOCKED_FAMILIES", "IpAddress", "blocked_reason", "resolve_addresses"]
