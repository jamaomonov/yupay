"""Receiving-address checks: TRON base58check, and EVM with its EIP-55 checksum.

A typo in the receiving address would send every reseller's money to a
stranger, so the admin form refuses anything whose checksum does not hold.
An EVM address must come checksummed (mixed case, as wallets show it): an
all-lowercase one carries no checksum, and a typo in it cannot be caught.
"""

from __future__ import annotations

import hashlib
import re
from typing import Final

from yupay.modules.usdt.keccak import keccak256

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


_EVM: Final = re.compile(r"0x[0-9a-fA-F]{40}")


def evm_checksum(address: str) -> str:
    """The EIP-55 spelling of a ``0x`` + 40-hex address."""
    body = address[2:].lower()
    digest = keccak256(body.encode()).hex()
    return "0x" + "".join(
        c.upper() if c.isalpha() and int(digest[i], 16) >= 8 else c for i, c in enumerate(body)
    )


def is_evm_address(value: str) -> bool:
    """Whether ``value`` is a checksummed EVM address (EIP-55, mixed case)."""
    if not _EVM.fullmatch(value):
        return False
    body = value[2:]
    if body.lower() == body or body.upper() == body:
        return False
    return evm_checksum(value) == value


def is_address(kind: str, value: str) -> bool:
    """The check for a network's ``kind`` (``tron`` or ``evm``)."""
    return is_tron_address(value) if kind == "tron" else is_evm_address(value)


__all__ = ["evm_checksum", "is_address", "is_evm_address", "is_tron_address"]
