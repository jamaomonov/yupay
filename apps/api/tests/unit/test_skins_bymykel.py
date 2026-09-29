"""ByMykel entries become catalogue rows; duplicates collapse; a missing
market_hash_name is skipped rather than crashing the whole import."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from yupay.modules.skins.bymykel import CatalogRow, dedupe, rows_from_file, rows_from_skins

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skins"


def _load(name: str) -> list[dict[str, object]]:
    return json.loads((FIXTURES / name).read_text())  # type: ignore[no-any-return]


def test_skin_rows_carry_taxonomy_and_phase() -> None:
    rows = rows_from_skins(_load("bymykel_skins.json"))
    by_slug = {row.slug: row for row in rows}
    ak = by_slug["ak-47-redline-field-tested"]
    assert (ak.category, ak.weapon, ak.skin, ak.exterior) == ("rifles", "AK-47", "Redline", "FT")
    assert (ak.stattrak, ak.phase, ak.paint_index) == (False, "", 282)
    assert (ak.min_float, ak.max_float) == (Decimal("0.1"), Decimal("0.7"))
    assert ak.rarity == "Classified"
    assert ak.rarity_color == "#d32ce6"
    assert ak.image_url == "https://community.akamai.steamstatic.com/economy/image/ak47redline"
    assert by_slug["stattrak-ak-47-redline-field-tested"].stattrak is True
    knife = by_slug["karambit-doppler-factory-new-phase-2"]
    assert (knife.category, knife.weapon, knife.phase) == ("knives", "Karambit", "Phase 2")
    assert knife.market_hash_name == "★ Karambit | Doppler (Factory New)"


def test_non_skin_file_rows_take_the_file_category() -> None:
    rows = rows_from_file("agents", _load("bymykel_agents.json"))
    assert len(rows) == 1
    assert rows[0].category == "agents"
    assert rows[0].weapon is None
    assert rows[0].search_text == "bloody darryl the strapped the professionals"


def test_entry_without_market_hash_name_is_skipped() -> None:
    assert rows_from_file("keys", [{"id": "k", "name": "no market name"}]) == []


def test_dedupe_keeps_the_first_of_a_name_and_phase() -> None:
    rows = rows_from_skins(_load("bymykel_skins.json"))
    doubled = [*rows, rows[0]]
    kept = dedupe(doubled)
    assert len(kept) == len(rows)
    assert all(isinstance(row, CatalogRow) for row in kept)


def test_an_agent_carries_its_side() -> None:
    rows = rows_from_file(
        "agents",
        [
            {"market_hash_name": "Bloody Darryl | The Professionals", "team": {"id": "terrorists"}},
            {"market_hash_name": "Cmdr. Mae | SWAT", "team": {"id": "counter-terrorists"}},
            {"market_hash_name": "Someone | Nobody"},
        ],
    )
    assert [r.team for r in rows] == ["t", "ct", None]


def test_a_weapon_has_no_side() -> None:
    rows = rows_from_skins(
        [{"market_hash_name": "AK-47 | Redline (Field-Tested)", "weapon": {"name": "AK-47"}}]
    )
    assert rows[0].team is None
