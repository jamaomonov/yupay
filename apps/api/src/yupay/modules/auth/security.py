"""Small cryptographic helpers used across the auth module.

Anything that has to be replay-safe, constant-time, or peppered lives here so that the
service and HTTP layers cannot accidentally re-implement it differently.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets


def sha256_hex(data: bytes) -> str:
    """Return a hex-encoded SHA-256 digest of ``data``."""
    return hashlib.sha256(data).hexdigest()


def hash_token(token: str) -> str:
    """Hash a refresh token for storage. Never store plaintext tokens."""
    return sha256_hex(token.encode("utf-8"))


def constant_time_eq(a: str, b: str) -> bool:
    """Constant-time string equality. Use for any secret comparison."""
    return hmac.compare_digest(a, b)


def email_hash(email: str, pepper: str) -> str:
    """Stable, peppered SHA-256 hash of a normalised email.

    Used as the ``sub`` of guest JWTs and as a logging-safe identifier. Lower-cases and
    strips the input — the wire format never contains the raw email.
    """
    normalised = email.strip().lower().encode("utf-8")
    pepper_bytes = pepper.encode("utf-8")
    return sha256_hex(pepper_bytes + b":" + normalised)


def new_refresh_token() -> str:
    """Mint a fresh, URL-safe refresh token (43 chars, 256 bits of entropy)."""
    return secrets.token_urlsafe(32)
