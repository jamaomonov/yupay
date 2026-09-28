"""Deterministic parsing of CS2 market hash names.

The market hash name is the join key between our catalogue (ByMykel) and
Waxpeer's listings, and the two feeds spell one thing differently: Waxpeer
writes a Doppler phase *inside* the name (``★ Karambit | Doppler Phase 2
(Factory New)``), ByMykel keeps ``market_hash_name`` phase-less and carries
``phase`` beside it. :func:`canonical_name` moves every name to the second
form; everything else here is derived from that canonical pair.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

EXTERIOR_CODES: dict[str, str] = {
    "Factory New": "FN",
    "Minimal Wear": "MW",
    "Field-Tested": "FT",
    "Well-Worn": "WW",
    "Battle-Scarred": "BS",
}
PHASES: tuple[str, ...] = (
    "Phase 1",
    "Phase 2",
    "Phase 3",
    "Phase 4",
    "Ruby",
    "Sapphire",
    "Emerald",
    "Black Pearl",
)

_STAR = "★ "
_STATTRAK = "StatTrak™ "
_SOUVENIR = "Souvenir "
_PHASE_RE = re.compile(
    r"^(?P<base>.*\| (?:Gamma )?Doppler) (?P<phase>Phase [1-4]|Ruby|Sapphire|Emerald|Black Pearl)"
    r"(?P<rest>(?: \([^()]*\))?)$"
)
_EXTERIOR_RE = re.compile(
    r"^(?P<body>.*) \((?P<ext>Factory New|Minimal Wear|Field-Tested|Well-Worn|Battle-Scarred)\)$"
)
_NON_SLUG = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class ParsedName:
    """A market hash name taken apart. ``phase`` is ``''`` when there is none."""

    market_hash_name: str
    phase: str
    stattrak: bool
    souvenir: bool
    star: bool
    weapon: str | None
    skin: str | None
    exterior: str | None


def canonical_name(raw: str) -> tuple[str, str]:
    """Return ``(market_hash_name, phase)`` with any inline Doppler phase moved out."""
    name = raw.strip()
    match = _PHASE_RE.match(name)
    if match is None:
        return name, ""
    return f"{match.group('base')}{match.group('rest')}", match.group("phase")


def parse_market_name(raw: str) -> ParsedName:
    """Split a name into its flags, weapon, skin and exterior."""
    name, phase = canonical_name(raw)
    body = name
    star = body.startswith(_STAR)
    if star:
        body = body[len(_STAR) :]
    stattrak = body.startswith(_STATTRAK)
    if stattrak:
        body = body[len(_STATTRAK) :]
    souvenir = body.startswith(_SOUVENIR)
    if souvenir:
        body = body[len(_SOUVENIR) :]
    exterior: str | None = None
    ext_match = _EXTERIOR_RE.match(body)
    if ext_match is not None:
        body = ext_match.group("body")
        exterior = EXTERIOR_CODES[ext_match.group("ext")]
    weapon: str | None = None
    skin: str | None = None
    if " | " in body and not body.startswith(("Sticker", "Sealed Graffiti", "Patch", "Charm")):
        weapon, skin = (part.strip() for part in body.split(" | ", 1))
    elif star:
        weapon = body.strip()
    return ParsedName(
        market_hash_name=name,
        phase=phase,
        stattrak=stattrak,
        souvenir=souvenir,
        star=star,
        weapon=weapon or None,
        skin=skin or None,
        exterior=exterior,
    )


def _ascii_fold(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.replace("★", " ").replace("™", " "))
    return folded.encode("ascii", "ignore").decode("ascii").lower()


def slug_for(market_hash_name: str, phase: str) -> str:
    """``ak-47-redline-field-tested``; the phase is appended when present."""
    text = _ascii_fold(market_hash_name)
    if phase:
        text = f"{text} {phase.lower()}"
    return _NON_SLUG.sub("-", text).strip("-")


def search_text(market_hash_name: str, phase: str) -> str:
    """Lower-case words only — what the trigram index and the alias expansion see."""
    text = _ascii_fold(market_hash_name)
    if phase:
        text = f"{text} {phase.lower()}"
    return " ".join(_NON_SLUG.sub(" ", text).split())


__all__ = [
    "EXTERIOR_CODES",
    "PHASES",
    "ParsedName",
    "canonical_name",
    "parse_market_name",
    "search_text",
    "slug_for",
]
