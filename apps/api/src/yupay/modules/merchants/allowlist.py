"""Parsing an API key's IP allowlist — one copy, two schema files.

`schemas.ApiKeyCreateIn` (the admin surface) and
`cabinet_schemas.CabinetApiKeyCreateIn` (the merchant's own) accept the same
field and must accept exactly the same strings. A second validator would be a
second table of what an address is, and the failure it produces is silent: an
entry this side accepts and `auth.address_allowed` cannot match locks a
merchant out of their own API with a 403 nobody can explain.

Its own module rather than a helper on either schema file, so neither has to
import the other and no import cycle is possible.
"""

from __future__ import annotations

import ipaddress
from typing import Final

#: `auth.address_allowed` walks the list on every machine-API request, so the
#: bound is a request-path cost rather than a storage one.
MAX_ENTRIES: Final = 32


def normalize_allowlist(value: list[str] | None) -> list[str] | None:
    """Trim, validate and collapse an allowlist to what the auth path reads.

    Args:
        value: Raw entries as the caller typed them, or ``None`` for no filter.

    Returns:
        The cleaned entries, or ``None`` when there are none — an empty list
        is normalised away so the "no addresses at all" shape, which would
        refuse every request, can never reach ``auth.address_allowed``.

    Raises:
        ValueError: An entry ``ipaddress`` cannot read. Rejected at the parse
            boundary, because stored verbatim it would never match.
    """
    if value is None:
        return None
    cleaned: list[str] = []
    for raw in value:
        entry = raw.strip()
        try:
            # ``strict=False``: host bits are allowed (``203.0.113.5/24``) and
            # read as the network at match time, the same as the auth path.
            ipaddress.ip_network(entry, strict=False)
        except ValueError:
            raise ValueError(f"not an IP address or CIDR block: {entry!r}") from None
        cleaned.append(entry)
    return cleaned or None


__all__ = ["MAX_ENTRIES", "normalize_allowlist"]
