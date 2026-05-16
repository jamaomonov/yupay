"""UUIDv7 helpers — sortable, index-friendly identifiers generated app-side."""

from __future__ import annotations

import uuid_utils


def new_id() -> str:
    """Return a new UUIDv7 as a 36-char string."""
    return str(uuid_utils.uuid7())
