"""Short public number for a top-up reservation: ``T`` + 7 Crockford characters.

Random, not sequential — a sequence would tell anyone holding two numbers how
many top-ups happened in between. 32^7 ≈ 3.4·10^10; the unique index catches
the collision this makes vanishingly rare, and the caller retries.
"""

from __future__ import annotations

import secrets
from typing import Final

ALPHABET: Final = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_reservation_number() -> str:
    """A fresh ``T…`` number."""
    return "T" + "".join(secrets.choice(ALPHABET) for _ in range(7))


__all__ = ["ALPHABET", "new_reservation_number"]
