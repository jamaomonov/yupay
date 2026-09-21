"""Which operator notes reach the reseller's statement, and which never do.

``transactions._operator_note`` is the whole gate between an admin's free
text and a third party's screen, so it is pinned here rather than only
through the endpoint: the interesting cases are all about a ``metadata``
blob that no schema validates.

The rule it enforces is in ``deposit.NOTE_VISIBLE_KEY`` — exposure begins at
the write. Rows booked while the admin form promised «видно только нам»
carry no flag and stay internal forever; only a movement written after that
promise changed is published.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from yupay.modules.merchants import deposit
from yupay.modules.merchants.transactions import _operator_note


def _txn(metadata: dict[str, Any]) -> Any:
    """A stand-in for the one attribute the function reads."""
    return SimpleNamespace(extra_metadata=metadata)


def test_a_flagged_note_is_published() -> None:
    assert (
        _operator_note(
            _txn(
                {deposit.OPERATOR_NOTE_KEY: "ошибочное пополнение", deposit.NOTE_VISIBLE_KEY: True}
            )
        )
        == "ошибочное пополнение"
    )


def test_a_note_written_before_the_flag_stays_internal() -> None:
    # The shape of every row already in production: a note, no flag.
    assert _operator_note(_txn({deposit.OPERATOR_NOTE_KEY: "внутренняя заметка"})) is None


def test_a_falsy_flag_is_not_a_flag() -> None:
    # `is not True`, not truthiness: a JSON blob can hold anything, and
    # "note_visible_to_merchant": "no" must not read as consent.
    for flag in (False, "no", 0, None, "true"):
        assert (
            _operator_note(_txn({deposit.OPERATOR_NOTE_KEY: "x", deposit.NOTE_VISIBLE_KEY: flag}))
            is None
        )


def test_the_system_posts_no_note_at_all() -> None:
    # An order charge and a refund carry an empty metadata blob; they explain
    # themselves through `order_id`.
    assert _operator_note(_txn({})) is None


def test_whitespace_is_not_an_explanation() -> None:
    assert (
        _operator_note(_txn({deposit.OPERATOR_NOTE_KEY: "   ", deposit.NOTE_VISIBLE_KEY: True}))
        is None
    )


def test_a_non_string_note_is_refused_rather_than_rendered() -> None:
    assert (
        _operator_note(_txn({deposit.OPERATOR_NOTE_KEY: 42, deposit.NOTE_VISIBLE_KEY: True}))
        is None
    )
