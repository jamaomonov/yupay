"""A card's full number, sealed at rest."""

from __future__ import annotations

import re

from yupay.core.crypto import decrypt, encrypt
from yupay.core.errors import ValidationError
from yupay.modules.p2p.models import P2PCard

_PURPOSE = "p2p_card_pan"


def normalize_pan(raw: str) -> str:
    """Digits only, exactly 16, or a 422 the admin form can show."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) != 16:
        raise ValidationError("card number must be 16 digits", code="p2p_pan_invalid")
    return digits


def seal_pan(pan: str) -> tuple[bytes, bytes]:
    """Encrypt a normalized number. Returns ``(ciphertext, nonce)``."""
    return encrypt(pan, purpose=_PURPOSE)


def open_pan(card: P2PCard) -> str:
    """The full number, for the one response that must carry it."""
    return decrypt(card.pan_ciphertext, card.pan_nonce, purpose=_PURPOSE)


__all__ = ["normalize_pan", "open_pan", "seal_pan"]
