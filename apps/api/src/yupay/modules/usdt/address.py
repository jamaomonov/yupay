"""TRON address check: base58check, 25 bytes, version byte 0x41.

A typo in the receiving address would send every reseller's money to a
stranger, so the admin form refuses anything whose checksum does not hold.
"""

from __future__ import annotations

import hashlib
from typing import Final

_ALPHABET: Final = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_INDEX: Final = {c: i for i, c in enumerate(_ALPHABET)}
_MAINNET_PREFIX: Final = 0x41


def _b58decode(value: str) -> bytes | None:
    num = 0
    for ch in value:
        digit = _INDEX.get(ch)
        if digit is None:
            return None
        num = num * 58 + digit
    body = num.to_bytes((num.bit_length() + 7) // 8, "big") if num else b""
    pad = len(value) - len(value.lstrip("1"))
    return b"\x00" * pad + body


def is_tron_address(value: str) -> bool:
    """Whether ``value`` is a well-formed mainnet TRON address (``T…``, 34 chars).

    Args:
        value: The candidate address.

    Returns:
        True only when the base58 decodes to 25 bytes with prefix ``0x41`` and
        the trailing four bytes equal the double-SHA-256 checksum.
    """
    if len(value) != 34 or not value.startswith("T"):
        return False
    raw = _b58decode(value)
    if raw is None or len(raw) != 25 or raw[0] != _MAINNET_PREFIX:
        return False
    payload, checksum = raw[:21], raw[21:]
    digest = hashlib.sha256(hashlib.sha256(payload).digest()).digest()
    return digest[:4] == checksum


__all__ = ["is_tron_address"]
