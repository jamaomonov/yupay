"""@HUMOcardbot notifications, as Telegram delivers them (spec §3)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from yupay.modules.p2p.parsing import parse_humo

TASHKENT = ZoneInfo("Asia/Tashkent")

CREDIT = (
    "🎉 Пополнение\n➕ 1.004,00 UZS\n📍 UB P2P Uzcard2Humo>T\n"
    "💳 HUMOCARD *3311\n🕓 04:47 04.10.2026\n💰 1.272.764,21 UZS"
)
CREDIT_TIYIN = (
    "🎉 Пополнение\n➕ 54.728,28 UZS\n📍 TBC P2P S UZCARD NA\n"
    "💳 HUMOCARD *3311\n🕓 19:53 03.10.2026\n💰 1.166.254,21 UZS"
)
DEBIT = (
    "💸 Оплата\n➖ 26.500,00 UZS\n📍 SOME SHOP TAS\n"
    "💳 HUMOCARD *3311\n🕓 12:01 04.10.2026\n💰 1.246.264,21 UZS"
)


def test_a_credit_is_read_whole() -> None:
    n = parse_humo(CREDIT)
    assert n.kind == "credit"
    assert n.amount == Decimal("1004.00")
    assert n.source == "UB P2P Uzcard2Humo>T"
    assert n.card_last4 == "3311"
    assert n.bank_time == datetime(2026, 10, 4, 4, 47, tzinfo=TASHKENT)
    assert n.balance_after == Decimal("1272764.21")


def test_tiyin_survive() -> None:
    assert parse_humo(CREDIT_TIYIN).amount == Decimal("54728.28")


def test_a_minus_line_is_a_debit() -> None:
    n = parse_humo(DEBIT)
    assert n.kind == "debit"
    assert n.amount == Decimal("26500.00")
    assert n.balance_after == Decimal("1246264.21")


def test_anything_else_is_unparsed() -> None:
    for text in ("", "Привет", "🎉 Пополнение\n➕ много UZS", "➕ 1.004,00 UZS"):
        assert parse_humo(text).kind == "unparsed"


@given(st.integers(min_value=0, max_value=10**11), st.integers(min_value=0, max_value=99))
def test_any_formatted_amount_round_trips(whole: int, tiyin: int) -> None:
    grouped = f"{whole:,}".replace(",", ".")
    text = CREDIT.replace("1.004,00", f"{grouped},{tiyin:02d}")
    assert parse_humo(text).amount == Decimal(f"{whole}.{tiyin:02d}")


def test_a_source_line_cannot_override_the_card_or_the_time() -> None:
    text = (
        "🎉 Пополнение\n➕ 1.004,00 UZS\n📍 SHOP *9999 01:00 01.01.2020\n"
        "💳 HUMOCARD *3311\n🕓 04:47 04.10.2026\n💰 1.272.764,21 UZS"
    )
    n = parse_humo(text)
    assert n.card_last4 == "3311"
    assert n.bank_time == datetime(2026, 10, 4, 4, 47, tzinfo=TASHKENT)


@pytest.mark.parametrize("when", ["99:99 31.02.2026", "24:00 04.10.2026", "12:00 31.02.2026"])
def test_an_impossible_time_is_unparsed(when: str) -> None:
    assert parse_humo(CREDIT.replace("04:47 04.10.2026", when)).kind == "unparsed"


@pytest.mark.parametrize(
    "line", ["💰 1.272.764,21 UZS", "💳 HUMOCARD *3311", "🕓 04:47 04.10.2026"]
)
def test_a_message_missing_one_required_line_is_unparsed(line: str) -> None:
    assert parse_humo(CREDIT.replace(f"\n{line}", "")).kind == "unparsed"


def test_non_ascii_digits_never_parse() -> None:
    assert parse_humo(CREDIT.replace("*3311", "*٣٣١١")).kind == "unparsed"
    assert parse_humo(CREDIT.replace("04:47", "٠٤:٤٧")).kind == "unparsed"
