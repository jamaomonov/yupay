"""``cards.normalize_pan`` and ``settings.admits`` (pure helpers)."""

from __future__ import annotations

import pytest
from yupay.core.errors import AppError
from yupay.modules.p2p.cards import normalize_pan
from yupay.modules.p2p.models import P2PSettings
from yupay.modules.p2p.settings import admits


@pytest.mark.parametrize(
    "raw",
    ["9860350146023311", "9860 3501 4602 3311", "9860-3501-4602-3311", " 9860 3501-4602 3311 "],
    ids=["plain", "spaces", "dashes", "mixed"],
)
def test_spaces_and_dashes_are_accepted(raw: str) -> None:
    assert normalize_pan(raw) == "9860350146023311"


@pytest.mark.parametrize(
    "raw",
    ["986035014602331", "98603501460233110", "9860 3501 4602 33ab", "", "abcd"],
    ids=["15-digits", "17-digits", "letters", "empty", "only-letters"],
)
def test_anything_but_16_digits_is_rejected(raw: str) -> None:
    with pytest.raises(AppError) as err:
        normalize_pan(raw)
    assert err.value.extra.get("code") == "p2p_pan_invalid"
    assert err.value.status_code == 422


def _settings(mode: str, allow: list[str] | None = None) -> P2PSettings:
    return P2PSettings(id=1, mode=mode, allowlist_merchant_ids=allow or [])


@pytest.mark.parametrize(
    ("mode", "allow", "expected"),
    [
        ("off", ["m1"], False),
        ("allowlist", ["m0", "m1"], True),
        ("allowlist", ["m0"], False),
        ("all", [], True),
    ],
    ids=["off", "allowlist-hit", "allowlist-miss", "all"],
)
def test_admits(mode: str, allow: list[str], expected: bool) -> None:
    assert admits(_settings(mode, allow), "m1") is expected
