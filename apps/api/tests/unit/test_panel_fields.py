"""NOVA's ``fields`` payload, built from NOVA's own declaration.

Order ``01a0ce52`` (Honkai Star Rail, 2026-09-23) was refused with
``Field "server" is required.`` — we had renamed our ``server`` to their
``server_id``, which is what Mobile Legends wants and not what Honkai wants.

Every spec below is copied from a live
``GET /api/v2/topups/offers?category_id=…`` read the same day, because the
point of this module is that the shape is *theirs*. Across the twenty
categories we map it takes four forms, and the fixed rename this replaces got
two of them right.
"""

from __future__ import annotations

from typing import Any

import pytest
from yupay.modules.fulfillment.suppliers.panel_fields import build_fields, field_specs

# --- the four real shapes, verbatim from their API ---------------------------

FREE_FIRE: list[dict[str, Any]] = [{"key": "player_id", "label": "Player ID", "type": "text"}]

MOBILE_LEGENDS: list[dict[str, Any]] = [
    {"key": "player_id", "label": "Player ID", "type": "text"},
    {"key": "server_id", "label": "Server ID", "type": "text"},
]

HONKAI: list[dict[str, Any]] = [
    {"key": "player_id", "label": "Player ID", "type": "text"},
    {
        "key": "server",
        "label": "Server",
        "type": "select",
        "options": [
            {"label": "Asia", "value": "asia"},
            {"label": "America", "value": "america"},
            {"label": "Europe", "value": "europe"},
            {"label": "TW,HK,MO", "value": "tw_hk_mo"},
        ],
    },
]

IMO: list[dict[str, Any]] = [{"key": "imo_id", "label": "IMO ID", "type": "text"}]


def test_the_refusal_this_module_exists_for() -> None:
    """Honkai wants ``server``, lower-case, and used to get ``server_id``."""
    built = build_fields(HONKAI, {"player_id": "801234567", "server": "Europe"})

    assert built == {"player_id": "801234567", "server": "europe"}


def test_mobile_legends_still_gets_the_key_it_always_wanted() -> None:
    """The rename was right here — reading their spec must not break it."""
    built = build_fields(MOBILE_LEGENDS, {"player_id": "123456789", "server": "12345"})

    assert built == {"player_id": "123456789", "server_id": "12345"}


def test_an_identifier_under_another_name() -> None:
    """IMO's ten NOVA-routed SKUs would have been refused for ``imo_id``.

    Our form calls it ``player_id`` and always will — it is the field a
    customer fills in, and «IMO ID» is what the label already says.
    """
    built = build_fields(IMO, {"player_id": "88001234567"})

    assert built == {"imo_id": "88001234567"}


def test_a_plain_category_is_unchanged() -> None:
    built = build_fields(FREE_FIRE, {"player_id": "10619597246"})

    assert built == {"player_id": "10619597246"}


def test_an_exact_key_match_beats_inference() -> None:
    """When their field is literally one of ours, no guessing is involved."""
    built = build_fields(IMO, {"imo_id": "111", "player_id": "222"})

    assert built == {"imo_id": "111"}


def test_a_select_matches_on_the_label_too() -> None:
    """The other direction: a form storing the human word, not the code."""
    built = build_fields(HONKAI, {"player_id": "1", "server": "TW,HK,MO"})

    assert built["server"] == "tw_hk_mo"


def test_an_unknown_choice_travels_unchanged() -> None:
    """Letting NOVA refuse it by name beats dropping the field silently — the
    refusal says which field is wrong, and a missing one does not."""
    built = build_fields(HONKAI, {"player_id": "1", "server": "Mars"})

    assert built["server"] == "Mars"


def test_a_field_we_cannot_fill_is_skipped_not_invented() -> None:
    """NOVA names the field it wants; guessing here would only hide that."""
    built = build_fields(HONKAI, {"player_id": "1"})

    assert built == {"player_id": "1"}


def test_no_declaration_is_not_the_same_as_no_fields() -> None:
    """``[]`` means they told us nothing, which every caller must read as
    "fall back", not as "this category needs nothing"."""
    assert field_specs({"ok": True, "offers": []}) == []
    assert field_specs({"fields": "nonsense"}) == []
    assert field_specs({"fields": [{"key": "player_id"}, "junk"]}) == [{"key": "player_id"}]


def test_a_field_with_no_key_is_ignored() -> None:
    specs: list[dict[str, Any]] = [{"label": "Mystery", "type": "text"}]

    assert build_fields(specs, {"player_id": "1"}) == {}


def test_a_field_we_cannot_place_is_left_alone() -> None:
    """Their key is neither a server nor an identifier — a captcha token, an
    email, whatever comes next. Guessing a value for it would send one of our
    fields under a name that means something else entirely.
    """
    specs: list[dict[str, Any]] = [
        {"key": "player_id", "type": "text"},
        {"key": "promo_code", "type": "text"},
    ]

    built = build_fields(specs, {"player_id": "1", "server": "europe"})

    assert built == {"player_id": "1"}


def test_the_server_role_covers_their_other_names_for_it() -> None:
    """``zone`` and ``region`` mean the same thing to a player and are spelled
    differently by suppliers — placing them by role is the point."""
    specs: list[dict[str, Any]] = [{"key": "zone", "type": "text"}]

    assert build_fields(specs, {"server": "12345"}) == {"zone": "12345"}


# --- Genshin: our form stores HoYoverse's region codes ------------------------

#: Verbatim from both fzr and NOVA, ``genshin_impact_global``, read 2026-09-25.
GENSHIN: list[dict[str, Any]] = [
    {"key": "player_id", "label": "Player ID", "type": "text"},
    {
        "key": "server",
        "label": "Server",
        "type": "select",
        "options": [
            {"label": "America", "value": "america"},
            {"label": "Asia", "value": "asia"},
            {"label": "Europe", "value": "europe"},
            {"label": "TW HK MO", "value": "tw_hk_mo"},
        ],
    },
]


@pytest.mark.parametrize(
    ("ours", "theirs"),
    [("os_usa", "america"), ("os_euro", "europe"), ("os_asia", "asia"), ("os_cht", "tw_hk_mo")],
)
def test_genshin_region_codes_become_their_words(ours: str, theirs: str) -> None:
    """Order ``01a0d68a`` (2026-09-25) was refused by fzr with ``Field "server":
    value must be one of the allowed options`` — we sent ``os_usa``.

    Our Genshin form keeps HoYoverse's own codes because G2B, the primary
    route, keys on them; neither the value nor the label of their options
    matches a code, so it has to be translated.
    """
    built = build_fields(GENSHIN, {"player_id": "701234567", "server": ours})

    assert built == {"player_id": "701234567", "server": theirs}


def test_a_region_code_is_still_matched_case_insensitively() -> None:
    built = build_fields(GENSHIN, {"player_id": "1", "server": "OS_EURO"})

    assert built["server"] == "europe"


def test_a_region_code_their_enum_lacks_travels_unchanged() -> None:
    """The alias only helps when its target is one of *their* options; if a
    vendor ever drops ``america``, the refusal should name ``os_usa``."""
    only_asia = [{**GENSHIN[1], "options": [{"label": "Asia", "value": "asia"}]}]

    assert build_fields(only_asia, {"server": "os_usa"}) == {"server": "os_usa"}
