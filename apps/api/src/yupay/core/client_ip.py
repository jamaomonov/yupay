"""Resolve the calling client's IP address.

Three consumers depend on getting the same answer — the global rate limiter
(``bootstrap``), the auth brute-force guard (``auth.ip_guard``), and the
chargeback evidence snapshot (``evidence``) — and they used to each carry their
own copy of this parsing. Divergence between them would be silent and would
matter: a limiter keyed on one value while evidence records another is a
liability, not a safeguard.

Why the FIRST entry of ``X-Forwarded-For`` can be trusted:

The shared edge proxy is the only hop in front of this app and it *overwrites*
the header rather than appending to it (``infra/edge/Caddyfile``), so a caller
cannot inject their own chain and pick an address. The app's own port is not
published, so no request reaches FastAPI around that proxy.

What it overwrites the header *with* depends on who the peer is, and the edge
decides that — not this function:

* a direct client is its own peer, so the value is ``{remote_host}``;
* behind Cloudflare (which YuPay hostnames were moved to on 2026-08-15, after a
  broken UZ↔OVH transit made the origin address unreachable from Uzbekistan and
  took Payme's webhooks down with it) the peer is a Cloudflare edge, so the
  value is ``CF-Connecting-IP`` — and that header is only trusted because the
  edge has already matched the peer against Cloudflare's published ranges.

Either way exactly one value arrives and it is the real client. If the edge is
ever changed to append instead of overwrite, or to read CF-Connecting-IP without
first proving the peer is Cloudflare, this function starts returning
attacker-controlled data and BOTH the guards and the evidence become worthless
— that config comment and this one are load-bearing together.
"""

from __future__ import annotations

from fastapi import Request

#: Recorded when the peer cannot be determined at all (ASGI without a client,
#: e.g. some test transports). Kept as a literal rather than None so callers
#: that key caches or columns on it don't have to special-case it.
UNKNOWN_IP = "unknown"


def client_ip(request: Request) -> str:
    """The client's address, or ``UNKNOWN_IP`` when there is no peer to read."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else UNKNOWN_IP


__all__ = ["UNKNOWN_IP", "client_ip"]
