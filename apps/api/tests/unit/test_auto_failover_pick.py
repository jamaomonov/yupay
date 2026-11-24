"""Which supplier a refused task moves to (ADR-0108)."""

from __future__ import annotations

from decimal import Decimal

from yupay.modules.fulfillment.auto_failover import pick_supplier


def _opt(slug: str, cost: str | None, stock: int | None = None) -> dict[str, object]:
    return {"supplier": slug, "cost_usdt": Decimal(cost) if cost else None, "stock": stock}


def _pick(options: list[dict[str, object]], previous: str | None = "9.00") -> tuple[object, str]:
    option, reason = pick_supplier(
        options,
        paid=Decimal("10.00"),
        previous_cost=Decimal(previous) if previous else None,
        min_margin_pct=Decimal("3"),
        max_step_pct=Decimal("6"),
    )
    return (option["supplier"] if option else None), reason  # type: ignore[index]


def test_the_cheapest_that_keeps_the_margin() -> None:
    assert _pick([_opt("g2b", "9.20"), _opt("nova", "9.50")]) == ("g2b", "")


def test_a_margin_below_three_percent_is_refused() -> None:
    # 10.00 paid, 3 % margin → at most 9.70.
    assert _pick([_opt("g2b", "9.80")], previous=None) == (None, "too_expensive")


def test_more_than_six_percent_over_the_old_cost_is_refused() -> None:
    # 9.00 × 1.06 = 9.54 caps it below the margin ceiling.
    assert _pick([_opt("g2b", "9.60")]) == (None, "too_expensive")


def test_out_of_stock_and_unpriced_are_skipped() -> None:
    assert _pick([_opt("g2b", "9.10", stock=0), _opt("nova", None), _opt("gengine", "9.30")]) == (
        "gengine",
        "",
    )
    assert _pick([_opt("nova", None)]) == (None, "no_priced_alternative")
