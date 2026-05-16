"""Idempotency-key middleware contract.

Every mutating endpoint accepts an ``Idempotency-Key`` header. Concrete middleware that
persists ``(key, route, user_id, request_hash, response_snapshot, status)`` will be added
when the first write endpoint lands. The constants below are the canonical key/header
names used across the codebase.
"""

from __future__ import annotations

IDEMPOTENCY_HEADER = "Idempotency-Key"
"""Canonical header name."""

IDEMPOTENCY_KEY_TTL_SECONDS = 24 * 60 * 60
"""How long we remember a response for replay (24 h)."""
