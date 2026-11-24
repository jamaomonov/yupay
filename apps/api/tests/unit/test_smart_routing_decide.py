"""The smart-routing rules for one SKU (ADR-0108)."""

from __future__ import annotations

from decimal import Decimal

from yupay.modules.sourcing.smart_routing import Candidate, Move, decide


def _c(slug: str, cost: str | None, stock: int | None = None, q: bool = False) -> Candidate:
    return Candidate(slug, Decimal(cost) if cost else None, stock, q)


def _decide(current: str | None, cands: list[Candidate], dwell_ok: bool = True) -> Move | None:
    return decide(
        current,
        cands,
        switch_pct=Decimal("1"),
        stock_step_pct=Decimal("6"),
        dwell_ok=dwell_ok,
    )


def _to(move: Move | None) -> tuple[str, str | None] | None:
    return (move.reason, move.to.supplier if move.to else None) if move else None


def test_one_percent_cheaper_moves() -> None:
    assert _to(_decide("fzr", [_c("fzr", "10.00"), _c("g2b", "9.90")])) == ("cheaper", "g2b")


def test_less_than_one_percent_stays() -> None:
    assert _decide("fzr", [_c("fzr", "10.00"), _c("g2b", "9.95")]) is None


def test_the_dwell_holds_a_cheaper_move_back() -> None:
    assert _decide("fzr", [_c("fzr", "10.00"), _c("g2b", "9.00")], dwell_ok=False) is None


def test_out_of_stock_moves_within_six_percent_even_in_the_dwell() -> None:
    cands = [_c("fzr", "10.00", stock=0), _c("g2b", "10.50")]
    assert _to(_decide("fzr", cands, dwell_ok=False)) == ("unavailable", "g2b")


def test_out_of_stock_with_only_dearer_alternatives_is_blocked() -> None:
    assert _to(_decide("fzr", [_c("fzr", "10.00", stock=0), _c("g2b", "10.70")])) == (
        "blocked",
        None,
    )


def test_a_quarantined_route_moves_and_nothing_moves_onto_quarantine() -> None:
    cands = [_c("fzr", "9.00", q=True), _c("g2b", "9.40"), _c("nova", "8.00", q=True)]
    assert _to(_decide("fzr", cands)) == ("unavailable", "g2b")


def test_a_route_with_no_mapping_is_left_alone() -> None:
    assert _decide("foxreload", [_c("waxpeer", "1.00")]) is None


def _stale(slug: str, cost: str) -> Candidate:
    return Candidate(slug, Decimal(cost), fresh=False)


def test_a_stale_current_price_decides_nothing() -> None:
    assert _decide("fzr", [_stale("fzr", "10.00"), _c("g2b", "9.00")]) is None


def test_a_stale_alternative_is_never_the_target() -> None:
    assert _decide("fzr", [_c("fzr", "10.00"), _stale("g2b", "9.00")]) is None


def test_a_far_cheaper_price_is_suspect_not_switched_to() -> None:
    assert _to(_decide("fzr", [_c("fzr", "10.00"), _c("g2b", "6.00")])) == ("suspicious", None)


def test_a_delisted_route_moves_even_with_a_stale_price() -> None:
    cands = [Candidate("fzr", Decimal("10.00"), fresh=False, listed=False), _c("g2b", "10.20")]
    assert _to(_decide("fzr", cands)) == ("unavailable", "g2b")
