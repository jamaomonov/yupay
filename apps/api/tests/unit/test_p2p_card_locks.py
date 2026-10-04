"""Which advisory locks a reservation takes before reading daily room (card_choice)."""

from __future__ import annotations

from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ClauseElement
from yupay.modules.p2p import card_choice
from yupay.modules.p2p.models import P2PCard

pytestmark = pytest.mark.asyncio


class _RecordingDb:
    """Collects the key of every ``pg_advisory_xact_lock`` it is asked to run."""

    def __init__(self) -> None:
        self.keys: list[int] = []

    async def execute(self, stmt: ClauseElement) -> None:
        params = stmt.compile().params
        assert len(params) == 1
        self.keys.append(int(next(iter(params.values()))))


def _card(card_id: str, limit: int | None) -> P2PCard:
    return P2PCard(id=card_id, daily_limit_uzs=limit)


async def _locked(cards: list[P2PCard]) -> list[int]:
    db = _RecordingDb()
    await card_choice._lock_limited(cast(AsyncSession, db), cards)  # duck-typed fake
    return db.keys


async def test_only_limited_cards_are_locked_once_each_in_key_order() -> None:
    cards = [
        _card("c-1", 30_000),
        _card("c-2", None),
        _card("c-3", 50_000),
        _card("c-1", 30_000),  # the same card twice: one lock
    ]
    expected = sorted({card_choice.card_lock_key("c-1"), card_choice.card_lock_key("c-3")})
    assert await _locked(cards) == expected
    assert card_choice.card_lock_key("c-2") not in expected


async def test_no_limited_card_takes_no_lock() -> None:
    assert await _locked([_card("c-1", None), _card("c-2", None)]) == []


def test_the_lock_key_is_stable_and_a_signed_int64() -> None:
    key = card_choice.card_lock_key("0190a0b0-0000-7000-8000-000000000001")
    assert key == card_choice.card_lock_key("0190a0b0-0000-7000-8000-000000000001")
    assert -(2**63) <= key < 2**63
    assert key != card_choice.card_lock_key("0190a0b0-0000-7000-8000-000000000002")
