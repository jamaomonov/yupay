"""Unit tests for the JWT issuance + verification helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from yupay.core import clock
from yupay.core.config import get_settings
from yupay.core.errors import UnauthorizedError
from yupay.modules.auth import jwt as authjwt


@pytest.fixture
def settings():
    """Fresh settings for each test."""
    get_settings.cache_clear()
    return get_settings()


def test_mint_and_verify_access_round_trip(settings) -> None:
    token = authjwt.mint_access(sub="user-1", sid="sess-1", settings=settings)
    claims = authjwt.verify(token, expected_kind="access", settings=settings)
    assert claims.sub == "user-1"
    assert claims.sid == "sess-1"
    assert claims.kind == "access"
    assert claims.jti  # non-empty UUIDv7


def test_mint_access_with_optional_claims(settings) -> None:
    token = authjwt.mint_access(
        sub="user-1",
        sid="sess-1",
        tg_id=42,
        email_hash="deadbeef",
        settings=settings,
    )
    claims = authjwt.verify(token, expected_kind="access", settings=settings)
    assert claims.tg_id == 42
    assert claims.email_hash == "deadbeef"


def test_mint_guest_token(settings) -> None:
    token = authjwt.mint_guest(email_hash="abc123", settings=settings)
    claims = authjwt.verify(token, expected_kind="guest", settings=settings)
    assert claims.kind == "guest"
    assert claims.sub == "guest:abc123"
    assert claims.email_hash == "abc123"
    assert "orders:create" in claims.scope


def test_verify_rejects_wrong_kind(settings) -> None:
    token = authjwt.mint_access(sub="user-1", sid="s", settings=settings)
    with pytest.raises(UnauthorizedError):
        authjwt.verify(token, expected_kind="refresh", settings=settings)


def test_verify_rejects_garbage(settings) -> None:
    with pytest.raises(UnauthorizedError):
        authjwt.verify("not.a.jwt", expected_kind="access", settings=settings)


def test_verify_rejects_expired_token(settings) -> None:
    """A token whose ``exp`` is in the past must be rejected."""
    fixed = datetime(2026, 1, 1, tzinfo=UTC)
    clock.set_clock(lambda: fixed)
    try:
        token = authjwt.mint_access(sub="u", sid="s", settings=settings)
    finally:
        clock.reset_clock()

    # Verifying much later — token is well past its 15-min lifetime.
    clock.set_clock(lambda: fixed + timedelta(hours=2))
    try:
        with pytest.raises(UnauthorizedError):
            authjwt.verify(token, expected_kind="access", settings=settings)
    finally:
        clock.reset_clock()


def test_ws_handshake_token_carries_channel(settings) -> None:
    token = authjwt.mint_ws_handshake(
        sub="user-1", sid="sess-1", channel="orders:user-1", settings=settings
    )
    claims = authjwt.verify(token, expected_kind="ws", settings=settings)
    assert claims.channel == "orders:user-1"
