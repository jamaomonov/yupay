"""Anonymous reader cookie: hash and mint rules."""

from __future__ import annotations

from yupay.modules.blog.engagement import hash_reader, resolve_reader


def test_hash_reader_is_stable_sha256() -> None:
    assert hash_reader("a" * 64) == hash_reader("a" * 64)
    assert len(hash_reader("a" * 64)) == 64
    assert hash_reader("a" * 64) != hash_reader("b" * 64)


def test_resolve_reader_keeps_a_valid_cookie() -> None:
    raw = "ab" * 32
    cookie, digest, minted = resolve_reader(raw)
    assert minted is False
    assert cookie == raw
    assert digest == hash_reader(raw)


def test_resolve_reader_replaces_garbage() -> None:
    cookie, digest, minted = resolve_reader("not-a-token")
    assert minted is True
    assert len(cookie) == 64
    assert digest == hash_reader(cookie)


def test_resolve_reader_replaces_a_non_ascii_cookie_instead_of_crashing() -> None:
    """``isalnum`` accepted 64 × «é», then ``hash_reader`` raised on encode: a 500."""
    from yupay.modules.blog.engagement import resolve_reader

    cookie, _digest, minted = resolve_reader("é" * 64)

    assert minted is True
    assert cookie != "é" * 64


def test_resolve_reader_replaces_uppercase_or_non_hex() -> None:
    from yupay.modules.blog.engagement import resolve_reader

    assert resolve_reader("Z" * 64)[2] is True
    assert resolve_reader("A" * 64)[2] is True
