"""Google sign-in: access-token verification.

The web keeps its own styled button (the official GIS widget clashed with
the dark modal and was reverted on sight), which rules out the ID-token
flow — Google only issues those through their widget. The custom button
runs the OAuth token popup instead and hands us an **access token**.

An access token proves nothing by itself: any app's token would pass a
naive userinfo call (token substitution). Verification therefore starts at
Google's ``tokeninfo``, which names the **audience** the token was minted
for — it must be OUR client id — and carries ``email``/``email_verified``.
``userinfo`` then fills in the display name and avatar, best-effort.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from yupay.core.config import get_settings

_TOKENINFO = "https://www.googleapis.com/oauth2/v3/tokeninfo"
_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"
_TIMEOUT_SECONDS = 10.0


class GoogleAuthError(Exception):
    """The token failed verification. Message is for logs, not clients."""


@dataclass(frozen=True)
class GoogleUser:
    """The verified identity, reduced to what the service layer uses."""

    sub: str
    email: str
    email_verified: bool
    name: str | None
    picture: str | None


async def verify_credential(
    access_token: str,
    *,
    client_id: str | None = None,
    http: httpx.AsyncClient | None = None,
) -> GoogleUser:
    """Verify a Google access token and return the identity.

    Raises:
        GoogleAuthError: Google refuses the token, the audience is not our
            client, or no usable email comes back.
        RuntimeError: ``GOOGLE_OAUTH_CLIENT_ID`` is not configured.
    """
    audience = client_id or get_settings().google_oauth_client_id
    if not audience:
        raise RuntimeError("GOOGLE_OAUTH_CLIENT_ID is not configured")

    client = http or httpx.AsyncClient(timeout=_TIMEOUT_SECONDS)
    try:
        try:
            info = await client.get(_TOKENINFO, params={"access_token": access_token})
        except httpx.HTTPError as exc:
            raise GoogleAuthError(f"tokeninfo unreachable: {exc}") from exc
        if info.status_code != 200:
            raise GoogleAuthError("google refused the token")
        claims = info.json()
        if claims.get("aud") != audience and claims.get("azp") != audience:
            raise GoogleAuthError("token was minted for another application")
        email = claims.get("email")
        sub = claims.get("sub")
        if not isinstance(email, str) or not email or not isinstance(sub, str):
            raise GoogleAuthError("token carries no usable identity")
        verified = (
            str(claims.get("email_verified", "")).lower() == "true"
            or claims.get("email_verified") is True
        )

        name: str | None = None
        picture: str | None = None
        try:
            profile = await client.get(
                _USERINFO, headers={"Authorization": f"Bearer {access_token}"}
            )
            if profile.status_code == 200:
                body = profile.json()
                raw_name = body.get("name")
                raw_picture = body.get("picture")
                name = raw_name if isinstance(raw_name, str) and raw_name else None
                picture = raw_picture if isinstance(raw_picture, str) and raw_picture else None
        except httpx.HTTPError:  # cosmetic only — nameless beats broken
            pass
    finally:
        if http is None:
            await client.aclose()

    return GoogleUser(sub=sub, email=email, email_verified=verified, name=name, picture=picture)


__all__ = ["GoogleAuthError", "GoogleUser", "verify_credential"]
