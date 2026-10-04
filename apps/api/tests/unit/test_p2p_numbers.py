"""Reservation number shape."""

from __future__ import annotations

from yupay.modules.p2p.numbers import ALPHABET, new_reservation_number


def test_shape() -> None:
    n = new_reservation_number()
    assert len(n) == 8
    assert n[0] == "T"
    assert set(n[1:]) <= set(ALPHABET)


def test_alphabet_has_no_lookalikes() -> None:
    assert not set("ILOU") & set(ALPHABET)
