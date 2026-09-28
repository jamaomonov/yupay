"""Our category slugs and the maps from both feeds onto them (spec §4.4)."""

from __future__ import annotations

from typing import Any

from yupay.modules.skins.naming import ParsedName

CATEGORY_SLUGS: tuple[str, ...] = (
    "rifles",
    "pistols",
    "smgs",
    "heavy",
    "knives",
    "gloves",
    "agents",
    "cases",
    "keys",
    "music-kits",
    "charms",
    "stickers",
    "graffiti",
    "patches",
    "collectibles",
    "highlights",
    "other",
)

#: ByMykel file key -> category. ``skins_not_grouped`` is decided per entry.
FILE_CATEGORIES: dict[str, str] = {
    "stickers": "stickers",
    "agents": "agents",
    "crates": "cases",
    "keys": "keys",
    "music_kits": "music-kits",
    "graffiti": "graffiti",
    "patches": "patches",
    "collectibles": "collectibles",
    "keychains": "charms",
    "highlights": "highlights",
}

_SKIN_CATEGORY_BY_NAME: dict[str, str] = {
    "Rifles": "rifles",
    "Pistols": "pistols",
    "SMGs": "smgs",
    "Heavy": "heavy",
    "Knives": "knives",
    "Gloves": "gloves",
}

_WAXPEER_TYPE_TO_CATEGORY: dict[str, str] = {
    "Rifles": "rifles",
    "Pistols": "pistols",
    "SMGs": "smgs",
    "Heavy": "heavy",
    "Knives": "knives",
    "Knife": "knives",
    "Gloves": "gloves",
    "Agents": "agents",
    "Case": "cases",
    "Crates": "cases",
    "Keys": "keys",
    "Music Kits": "music-kits",
    "Music Kit Box": "music-kits",
    "Weapon Charms": "charms",
    "Stickers": "stickers",
    "Sticker Capsule": "stickers",
    "Autograph Capsule": "stickers",
    "Graffities": "graffiti",
    "Graffiti": "graffiti",
    "Patches": "patches",
    "Patch Capsule": "patches",
    "Collectibles": "collectibles",
    "Pins": "collectibles",
    "Highlights": "highlights",
    "Souvenir Highlight": "highlights",
}


def category_for_skin(entry: dict[str, Any], parsed: ParsedName) -> str:
    """ByMykel's ``category.name`` when it maps; else the star heuristics; else ``other``."""
    category = entry.get("category")
    name = category.get("name") if isinstance(category, dict) else None
    if isinstance(name, str) and name in _SKIN_CATEGORY_BY_NAME:
        return _SKIN_CATEGORY_BY_NAME[name]
    if parsed.star and parsed.weapon is not None and parsed.weapon.endswith("Gloves"):
        return "gloves"
    if parsed.star and parsed.weapon is not None and "Wraps" in parsed.weapon:
        return "gloves"
    if parsed.star:
        return "knives"
    return "other"


def category_for_file(file_key: str) -> str:
    """Category for every non-skin ByMykel file; ``other`` for an unknown key."""
    return FILE_CATEGORIES.get(file_key, "other")


def category_for_waxpeer_type(type_name: str | None) -> str:
    """Category for a stub row created from a Waxpeer ``/v1/prices`` ``type``."""
    if type_name is None:
        return "other"
    return _WAXPEER_TYPE_TO_CATEGORY.get(type_name, "other")


__all__ = [
    "CATEGORY_SLUGS",
    "FILE_CATEGORIES",
    "category_for_file",
    "category_for_skin",
    "category_for_waxpeer_type",
]
