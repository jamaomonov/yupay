"""Partner authentication.

The property this file exists to hold is that a partner and a buyer cannot be
mistaken for one another. Everything else here — passwords, sessions, the
set-password link — is the project's existing machinery pointed at a second
kind of subject; this is the part that is genuinely new.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def test_a_partner_token_is_not_a_buyer_token() -> None:
    """The two token kinds must not be interchangeable.

    Reusing ``"access"`` for partners would work today only because a partner
    id is not found in ``users`` — an accident, not a boundary. It stops
    holding the moment anything resolves a subject less strictly.
    """
    from yupay.core.errors import UnauthorizedError
    from yupay.modules.auth import jwt as authjwt

    token = authjwt.mint_partner_access(sub="p-1", sid="s-1")
    assert authjwt.verify(token, expected_kind="partner_access").sub == "p-1"
    with pytest.raises(UnauthorizedError):
        authjwt.verify(token, expected_kind="access")

    buyer = authjwt.mint_access(sub="u-1", sid="s-1")
    with pytest.raises(UnauthorizedError):
        authjwt.verify(buyer, expected_kind="partner_access")
