"""Email-verify / password-reset JWT minting + verification."""

from __future__ import annotations

import pytest
from yupay.core.errors import UnauthorizedError
from yupay.modules.auth import jwt as authjwt


def test_email_verify_roundtrip() -> None:
    token = authjwt.mint_email_verify(sub="user-1")
    claims = authjwt.verify(token, expected_kind="email_verify")
    assert claims.sub == "user-1"
    assert claims.jti


def test_password_reset_roundtrip_has_jti() -> None:
    token = authjwt.mint_password_reset(sub="user-2")
    claims = authjwt.verify(token, expected_kind="password_reset")
    assert claims.sub == "user-2"
    assert claims.jti


def test_kind_mismatch_rejected() -> None:
    token = authjwt.mint_email_verify(sub="user-3")
    with pytest.raises(UnauthorizedError):
        authjwt.verify(token, expected_kind="password_reset")
