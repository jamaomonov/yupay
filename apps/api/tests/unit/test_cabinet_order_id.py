"""The cabinet's ``merchant_order_id``, derived from the browser's key.

The route used to mint a fresh one per call, so a retry of one click was a
second order and a second charge — while the cabinet's own client already
held one key per intent and sent it on every attempt.

What matters here is the shape as much as the determinism: the header is
client-controlled free text with only a minimum length enforced, and the id
it feeds is bounded at 128 printable non-space ASCII characters, becomes a
path segment, and is part of the signed string on the machine API.
"""

from __future__ import annotations

import re

from yupay.modules.merchants.cabinet_routes import _manual_order_id

#: `MerchantOrderCreateIn.merchant_order_id`, transcribed.
_WIRE = re.compile(r"^[\x21-\x7e]{1,128}$")


def test_one_key_is_one_order_id() -> None:
    key = "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34"
    assert _manual_order_id(key) == _manual_order_id(key)


def test_different_keys_do_not_collide() -> None:
    assert _manual_order_id("a" * 16) != _manual_order_id("b" * 16)


def test_no_key_still_yields_a_distinct_id_per_call() -> None:
    # The pre-existing behaviour, kept: with no header a double-click is two
    # orders a person can see and ask about, which beats an invented key
    # collapsing two real purchases into one.
    assert _manual_order_id(None) != _manual_order_id(None)


def test_the_prefix_the_three_frontend_screens_look_for_survives() -> None:
    for key in (None, "0198c3d1-4f2a-7b60-9c11-8e5d2a7f0b34"):
        assert _manual_order_id(key).startswith("manual-")


def test_a_hostile_header_cannot_shape_the_id() -> None:
    # Spaces, non-ASCII, a path separator and 400 characters: every one of
    # these would be refused by the wire schema, or worse, accepted into a
    # URL. The digest makes the shape ours whatever arrived.
    for key in (
        "has spaces in it",
        "../../etc/passwd" + "x" * 8,
        "ключ-кириллицей-длинный",
        "z" * 400,
        "tab\tseparated\tkey",
    ):
        got = _manual_order_id(key)
        assert _WIRE.match(got), got
        assert len(got) == 39
