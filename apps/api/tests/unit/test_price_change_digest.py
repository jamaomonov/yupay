"""The hourly price-change digest: one message, counts first, biggest moves, the rest as a number."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from yupay.modules.integrations.price_refresh import _DIGEST_TOP, _format_digest, _Move


def _move(code: str, old: str | None, new: str, **extra: Any) -> _Move:
    mapping = SimpleNamespace(sku_id="sku", supplier_slug="g2b")
    fields: dict[str, Any] = {
        "old_cost": None if old is None else Decimal(old),
        "new_cost": Decimal(new),
        "old_price": None,
        "new_price": None,
        "margin_percent": None,
        "price_drop_blocked": False,
        **extra,
    }
    outcome = SimpleNamespace(**fields)
    return _Move(mapping=mapping, sku_code=code, outcome=outcome)  # type: ignore[arg-type]


def test_digest_counts_directions_and_caps_the_list() -> None:
    moves = [_move(f"up-{i}", "1.00", "1.20") for i in range(8)]
    moves += [_move(f"down-{i}", "1.00", "0.80") for i in range(5)]
    moves.append(_move("fresh", None, "2.00"))

    text = _format_digest(moves, threshold=5.0)

    assert "14 изменений больше 5%" in text
    assert "выросла — 8" in text
    assert "снизилась — 5" in text
    assert "впервые — 1" in text
    assert text.count("\n• ") == _DIGEST_TOP
    assert f"… и ещё {14 - _DIGEST_TOP}" in text


def test_digest_line_keeps_the_words_an_operator_skims_for() -> None:
    rise = _move(
        "pubgm-60",
        "0.80",
        "0.90",
        old_price=Decimal("1.00"),
        new_price=Decimal("1.13"),
        margin_percent=Decimal("13"),
    )
    drop = _move("ff-110", "1.00", "0.70", price_drop_blocked=True)

    text = _format_digest([rise, drop], threshold=5.0)

    assert "себестоимость выросла +12.5%" in text
    assert "Цена USD: $1.00 → <b>$1.13</b> (наценка 13% сохранена)" in text
    assert "себестоимость снизилась -30.0%" in text
    assert "не снижена" in text
    # The biggest move leads, whichever direction it went.
    assert text.index("ff-110") < text.index("pubgm-60")
