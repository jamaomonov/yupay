"""Market hash names are parsed deterministically — the join key between
ByMykel rows and Waxpeer listings, so every case here is a real name from
one of the two feeds (2026-09-28)."""

from __future__ import annotations

import pytest
from yupay.modules.skins.naming import (
    canonical_name,
    parse_market_name,
    search_text,
    slug_for,
)
from yupay.modules.skins.taxonomy import (
    category_for_file,
    category_for_skin,
    category_for_waxpeer_type,
)


@pytest.mark.parametrize(
    ("raw", "name", "phase"),
    [
        ("AK-47 | Redline (Field-Tested)", "AK-47 | Redline (Field-Tested)", ""),
        (
            "★ Karambit | Doppler Phase 2 (Factory New)",
            "★ Karambit | Doppler (Factory New)",
            "Phase 2",
        ),
        (
            "★ StatTrak™ Butterfly Knife | Gamma Doppler Emerald (Factory New)",
            "★ StatTrak™ Butterfly Knife | Gamma Doppler (Factory New)",
            "Emerald",
        ),
        (
            "★ Nomad Knife | Doppler Ruby (Minimal Wear)",
            "★ Nomad Knife | Doppler (Minimal Wear)",
            "Ruby",
        ),
        (
            "Glock-18 | Gamma Doppler Emerald (Factory New)",
            "Glock-18 | Gamma Doppler (Factory New)",
            "Emerald",
        ),
        (
            "★ Shadow Daggers | Doppler Black Pearl (Factory New)",
            "★ Shadow Daggers | Doppler (Factory New)",
            "Black Pearl",
        ),
        ("Sticker | Aerial (Foil) | Katowice 2019", "Sticker | Aerial (Foil) | Katowice 2019", ""),
    ],
)
def test_canonical_name_strips_an_inline_phase(raw: str, name: str, phase: str) -> None:
    assert canonical_name(raw) == (name, phase)


def test_parse_plain_rifle() -> None:
    p = parse_market_name("AK-47 | Redline (Field-Tested)")
    assert (p.weapon, p.skin, p.exterior) == ("AK-47", "Redline", "FT")
    assert (p.stattrak, p.souvenir, p.star, p.phase) == (False, False, False, "")


def test_parse_stattrak_star_knife_with_phase() -> None:
    p = parse_market_name("★ StatTrak™ Karambit | Doppler Phase 4 (Factory New)")
    assert p.market_hash_name == "★ StatTrak™ Karambit | Doppler (Factory New)"
    assert (p.weapon, p.skin, p.exterior, p.phase) == ("Karambit", "Doppler", "FN", "Phase 4")
    assert (p.stattrak, p.star) == (True, True)


def test_parse_souvenir() -> None:
    p = parse_market_name("Souvenir AWP | Desert Hydra (Battle-Scarred)")
    assert (p.weapon, p.skin, p.exterior, p.souvenir) == ("AWP", "Desert Hydra", "BS", True)


def test_parse_gloves() -> None:
    p = parse_market_name("★ Sport Gloves | Hedge Maze (Field-Tested)")
    assert (p.weapon, p.skin, p.star) == ("Sport Gloves", "Hedge Maze", True)


def test_parse_vanilla_knife_has_no_skin() -> None:
    p = parse_market_name("★ Bayonet")
    assert (p.weapon, p.skin, p.exterior, p.star) == ("Bayonet", None, None, True)


def test_parse_case_and_sticker_have_no_weapon() -> None:
    assert parse_market_name("Kilowatt Case").weapon is None
    assert parse_market_name("Sticker | Aerial (Foil) | Katowice 2019").weapon is None


@pytest.mark.parametrize(
    ("name", "phase", "slug"),
    [
        ("AK-47 | Redline (Field-Tested)", "", "ak-47-redline-field-tested"),
        ("StatTrak™ AK-47 | Redline (Field-Tested)", "", "stattrak-ak-47-redline-field-tested"),
        ("★ Karambit | Doppler (Factory New)", "Phase 2", "karambit-doppler-factory-new-phase-2"),
        (
            "★ Karambit | Doppler (Factory New)",
            "Black Pearl",
            "karambit-doppler-factory-new-black-pearl",
        ),
        (
            "Souvenir AWP | Desert Hydra (Battle-Scarred)",
            "",
            "souvenir-awp-desert-hydra-battle-scarred",
        ),
        ("Sticker | Aerial (Foil) | Katowice 2019", "", "sticker-aerial-foil-katowice-2019"),
    ],
)
def test_slug_is_ascii_lowercase_and_carries_the_phase(name: str, phase: str, slug: str) -> None:
    assert slug_for(name, phase) == slug


def test_search_text_drops_decoration() -> None:
    assert search_text("★ StatTrak™ Karambit | Doppler (Factory New)", "Phase 2") == (
        "stattrak karambit doppler factory new phase 2"
    )


def test_category_for_skin_reads_bymykel_category_then_star_heuristics() -> None:
    p = parse_market_name("★ Sport Gloves | Hedge Maze (Field-Tested)")
    assert category_for_skin({"category": {"name": "Gloves"}}, p) == "gloves"
    assert category_for_skin({"category": {"name": "Rifles"}}, p) == "rifles"
    assert category_for_skin({}, p) == "gloves"
    assert category_for_skin({}, parse_market_name("★ Bayonet")) == "knives"
    assert category_for_skin({}, parse_market_name("AK-47 | Redline (Field-Tested)")) == "other"


def test_category_for_file_and_waxpeer_type() -> None:
    assert category_for_file("crates") == "cases"
    assert category_for_file("keychains") == "charms"
    assert category_for_waxpeer_type("Weapon Charms") == "charms"
    assert category_for_waxpeer_type("Graffities") == "graffiti"
    assert category_for_waxpeer_type("Knife") == "knives"
    assert category_for_waxpeer_type(None) == "other"
