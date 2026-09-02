"""Google sign-in: ID-token verification.

The web storefront renders Google's own GIS button; a successful sign-in
hands the page a **credential** — a JWT signed by Google. This module checks
that signature against Google's published keys and that the token was minted
for OUR OAuth client, and reduces the claims to the four fields the service
layer needs. Nothing else from the token is kept.

``google-auth`` performs the verification (already a dependency, ADR-0065);
its certificate fetch is blocking, so the check runs in a thread — this is
the login path, and a blocked event loop here queues every other request.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from yupay.core.config import get_settings


class GoogleAuthError(Exception):
    """The credential failed verification. Message is for logs, not clients."""


@dataclass(frozen=True)
class GoogleUser:
    """The verified identity, reduced to what the service layer uses."""

    sub: str
    email: str
    email_verified: bool
    name: str | None
    picture: str | None


async def verify_credential(credential: str, *, client_id: str | None = None) -> GoogleUser:
    """Verify a GIS credential (ID token) and return the identity.

    Raises:
        GoogleAuthError: Bad signature, wrong audience, expired token, or a
            token with no email claim.
        RuntimeError: ``GOOGLE_OAUTH_CLIENT_ID`` is not configured.
    """
    from google.auth.transport.requests import Request
    from google.oauth2 import id_token

    audience = client_id or get_settings().google_oauth_client_id
    if not audience:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID is not configured")

    def check() -> dict[str, object]:
        claims = id_token.verify_oauth2_token(  # type: ignore[no-untyped-call]
            credential, Request(), audience
        )
        assert isinstance(claims, dict)  # narrowed for mypy; the lib returns the payload
        return claims

    try:
        claims = await asyncio.to_thread(check)
    except Exception as exc:
        raise GoogleAuthError(str(exc)[:200]) from exc

    email = claims.get("email")
    sub = claims.get("sub")
    if not isinstance(email, str) or not email or not isinstance(sub, str):
        raise GoogleAuthError("token carries no usable identity")
    name = claims.get("name")
    picture = claims.get("picture")
    return GoogleUser(
        sub=sub,
        email=email,
        email_verified=bool(claims.get("email_verified")),
        name=name if isinstance(name, str) else None,
        picture=picture if isinstance(picture, str) else None,
    )


__all__ = ["GoogleAuthError", "GoogleUser", "verify_credential"]
