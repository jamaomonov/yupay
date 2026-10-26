"""A Free Fire hit from another region is refused; anything uncertain passes."""

from __future__ import annotations

from yupay.modules.integrations.player_check_region import apply, checks_region
from yupay.modules.integrations.schemas import PlayerCheckOut

HIT = PlayerCheckOut(status="valid", name="Neo")


def test_a_cis_account_on_the_bangladesh_page_is_wrong_region() -> None:
    out = apply(HIT, {"valid": "valid", "region": "RU"}, "bd")
    assert out.status == "invalid"
    assert out.reason == "wrong_region"
    assert out.account_regions == ["cis"]
    assert out.name == "Neo"


def test_the_accounts_own_region_passes() -> None:
    assert apply(HIT, {"region": "RU"}, "cis") == HIT
    assert apply(HIT, {"region": "SG"}, "mysg") == HIT


def test_nothing_uncertain_blocks() -> None:
    assert apply(HIT, {}, "bd") == HIT  # the CIS code sends no region
    assert apply(HIT, {"region": "ZZ"}, "bd") == HIT  # a region we do not know
    assert apply(HIT, {"region": "RU"}, "global") == HIT  # a page we cannot place
    assert apply(HIT, {"region": "RU"}, None) == HIT


def test_only_a_valid_verdict_is_compared() -> None:
    miss = PlayerCheckOut(status="invalid")
    assert apply(miss, {"region": "RU"}, "bd") == miss


def test_only_free_fire_games_carry_a_region() -> None:
    assert checks_region("freefire_bd")
    assert not checks_region("mlbb")
