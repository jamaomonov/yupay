"""Small cryptographic helpers used across the auth module.

Anything that has to be replay-safe, constant-time, or peppered lives here so that the
service and HTTP layers cannot accidentally re-implement it differently.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

import anyio
import anyio.to_thread
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError


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


_password_hasher = PasswordHasher()

#: What one argon2 call allocates, from the hasher's own parameters. Read rather
#: than hardcoded so the two can never drift.
ARGON2_MEMORY_MIB = _password_hasher.memory_cost // 1024

#: How many password operations may run at once.
#:
#: Moving argon2 to a threadpool without this trades one outage for a worse one:
#: anyio's default limiter is 40 threads, and at 64 MiB each that is 2.5 GB of
#: transient allocation against a 2g container limit on a host with no swap —
#: the OOM killer, which on this shared box may pick the neighbour stack's
#: database rather than us.
#:
#: Four is not about throughput. argon2 is CPU-bound, so concurrency cannot make
#: it finish sooner — measured, eight in parallel are slightly *slower* than
#: eight in series. What the threadpool buys is that the event loop keeps
#: serving everything else; what the cap buys is that a credential-stuffing
#: flood cannot turn that into 2.5 GB and every core.
PASSWORD_LIMITER = anyio.CapacityLimiter(4)


def hash_password_sync(plain: str) -> str:
    """Hash a plaintext password with argon2id. Blocking — see ``hash_password``.

    Public only so module-level constants can be built before an event loop
    exists (``service._DUMMY_HASH``). Anything on the request path must use the
    async wrapper.

    Args:
        plain: The user-supplied password.

    Returns:
        An encoded argon2id hash safe to persist (``$argon2id$...``).
    """
    return _password_hasher.hash(plain)


def verify_password_sync(plain: str, hashed: str) -> bool:
    """Verify a password against an argon2id hash. Blocking — see ``verify_password``.

    Returns ``False`` on any mismatch or malformed hash rather than raising, so
    callers can treat the result as a simple boolean.

    Args:
        plain: The user-supplied plaintext password.
        hashed: The stored argon2id hash string.

    Returns:
        ``True`` if the password matches the hash, ``False`` otherwise.
    """
    try:
        return _password_hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def hash_password(plain: str) -> str:
    """Hash a password on a worker thread.

    Async on purpose, and the async one is the *public* name so the blocking
    version cannot be reached by accident from a handler.

    argon2 is expensive by design — 98ms per call on the production box at
    ``memory_cost`` 64 MiB. The API runs a single uvicorn process, so calling it
    inline is not slow logins: it is the entire service serving nobody for a
    tenth of a second, catalog reads and payment webhooks included. That capped
    the whole API at roughly ten password operations a second. argon2-cffi
    releases the GIL inside its C call, so moving it to a thread genuinely
    parallelises rather than merely relocating the wait.

    Lowering ``memory_cost`` would have been the wrong fix twice over: the
    parameters are baked into every stored hash, so existing users keep paying
    the old cost until rehashed, and it buys speed by weakening the hash.
    """
    return await anyio.to_thread.run_sync(hash_password_sync, plain, limiter=PASSWORD_LIMITER)


async def verify_password(plain: str, hashed: str) -> bool:
    """Verify a password on a worker thread. See ``hash_password`` for why."""
    return await anyio.to_thread.run_sync(
        verify_password_sync, plain, hashed, limiter=PASSWORD_LIMITER
    )
