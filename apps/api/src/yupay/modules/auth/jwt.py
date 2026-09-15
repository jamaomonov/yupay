"""JWT issuance and verification (EdDSA / Ed25519).

See `docs/decisions/0007-jwt-format-and-rotation.md` for the token format, claims, and
rotation policy. This module is intentionally thin — it does **no** session lookups and
**no** revocation checks. Those belong in the service layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final, Literal, cast

import jwt
from jwt.exceptions import InvalidTokenError

from yupay.core.clock import now
from yupay.core.config import Settings, get_settings
from yupay.core.errors import UnauthorizedError
from yupay.core.ids import new_id

ALG: Final[str] = "EdDSA"

TokenKind = Literal[
    "access",
    "refresh",
    "guest",
    "guest_order",
    "ws",
    "email_verify",
    "password_reset",
    # Affiliate partners. A separate kind rather than reusing "access":
    # ``verify`` rejects a kind mismatch, which is what makes a partner
    # token structurally unusable on a buyer endpoint and a buyer token
    # unusable on the panel.
    "partner_access",
    # Merchant cabinet operators (spec §11). Same reasoning as the line above,
    # one actor further out: a reseller's operator is neither a buyer nor a
    # partner, and three kinds that reject each other are three mistakes the
    # type system makes for us.
    "merchant_access",
]


@dataclass(frozen=True)
class Claims:
    """Decoded JWT payload, narrowed to the fields YuPay cares about."""

    sub: str
    kind: TokenKind
    jti: str
    iat: datetime
    exp: datetime
    sid: str | None = None
    tg_id: int | None = None
    email_hash: str | None = None
    scope: tuple[str, ...] = ()
    channel: str | None = None
    order_id: str | None = None


def _settings_or(settings: Settings | None) -> Settings:
    return settings if settings is not None else get_settings()


def _encode(
    payload: dict[str, Any],
    *,
    settings: Settings,
) -> str:
    private_key = settings.jwt_private_key
    if not private_key:
        raise RuntimeError(
            "JWT_PRIVATE_KEY is not configured — refusing to mint tokens. "
            "Generate one with `./scripts/gen-secret.sh jwt`."
        )
    return jwt.encode(
        payload,
        private_key,
        algorithm=ALG,
        headers={"kid": settings.jwt_kid},
    )


def _base_payload(
    *,
    sub: str,
    kind: TokenKind,
    ttl_seconds: int,
    settings: Settings,
) -> dict[str, Any]:
    issued = now()
    return {
        "iss": settings.jwt_issuer,
        "sub": sub,
        "kind": kind,
        "jti": new_id(),
        "iat": int(issued.timestamp()),
        "exp": int((issued + timedelta(seconds=ttl_seconds)).timestamp()),
    }


def mint_access(
    *,
    sub: str,
    sid: str,
    tg_id: int | None = None,
    email_hash: str | None = None,
    settings: Settings | None = None,
) -> str:
    """Issue a short-lived access JWT for an authenticated user.

    The caller is responsible for ensuring ``sid`` references a non-revoked row in
    ``auth_sessions``.
    """
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub,
        kind="access",
        ttl_seconds=s.jwt_access_ttl_seconds,
        settings=s,
    )
    payload["sid"] = sid
    if tg_id is not None:
        payload["tg_id"] = tg_id
    if email_hash is not None:
        payload["email_hash"] = email_hash
    return _encode(payload, settings=s)


def mint_partner_access(
    *,
    sub: str,
    sid: str,
    settings: Settings | None = None,
) -> str:
    """Issue a short-lived access JWT for an authenticated **partner**.

    A distinct ``kind`` from :func:`mint_access` on purpose. ``verify`` rejects
    a kind mismatch, so this token cannot be presented to a buyer endpoint and
    a buyer's token cannot be presented to the panel. Relying instead on a
    partner id not existing in ``users`` would be an accident that holds only
    until something resolves a subject less strictly.

    Args:
        sub: The ``affiliate_partners`` row id.
        sid: The ``affiliate_sessions`` row this token belongs to. The caller
            is responsible for it being non-revoked.
        settings: Overrides the process settings; for tests.

    Returns:
        The encoded JWT.
    """
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub,
        kind="partner_access",
        ttl_seconds=s.affiliate_access_ttl_seconds,
        settings=s,
    )
    payload["sid"] = sid
    return _encode(payload, settings=s)


def mint_merchant_access(
    *,
    sub: str,
    sid: str,
    settings: Settings | None = None,
) -> str:
    """Issue a short-lived access JWT for an authenticated **merchant user**.

    Its own ``kind``, for the reason :func:`mint_partner_access` gives: a
    cabinet token must be structurally unusable on a buyer or partner endpoint
    and vice versa. Note what ``sub`` is — the ``merchant_users`` row, the
    person — not the ``merchants`` row. The cabinet resolves the company from
    the person on every request, so a user moved between merchants cannot keep
    acting for the old one on a token minted before the move.

    Args:
        sub: The ``merchant_users`` row id.
        sid: The ``merchant_sessions`` row this token belongs to. The caller is
            responsible for it being non-revoked.
        settings: Overrides the process settings; for tests.

    Returns:
        The encoded JWT.
    """
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub,
        kind="merchant_access",
        ttl_seconds=s.merchant_access_ttl_seconds,
        settings=s,
    )
    payload["sid"] = sid
    return _encode(payload, settings=s)


def mint_refresh(
    *,
    sub: str,
    sid: str,
    settings: Settings | None = None,
) -> str:
    """Issue a long-lived refresh JWT.

    The corresponding ``auth_sessions`` row stores ``SHA-256`` of the **opaque** refresh
    token actually shipped to the client (see ``security.new_refresh_token``). The JWT
    flavour here is reserved for environments that prefer JWT refresh; YuPay currently
    uses opaque tokens — keep this helper for completeness and future flexibility.
    """
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub,
        kind="refresh",
        ttl_seconds=s.jwt_refresh_ttl_seconds,
        settings=s,
    )
    payload["sid"] = sid
    return _encode(payload, settings=s)


def mint_guest(
    *,
    email_hash: str,
    scope: list[str] | None = None,
    settings: Settings | None = None,
) -> str:
    """Issue a single-purpose guest checkout token, bound to an email hash."""
    s = _settings_or(settings)
    payload = _base_payload(
        sub=f"guest:{email_hash}",
        kind="guest",
        ttl_seconds=s.jwt_guest_ttl_seconds,
        settings=s,
    )
    payload["email_hash"] = email_hash
    payload["scope"] = scope or ["orders:create", "orders:read:own"]
    return _encode(payload, settings=s)


def mint_guest_order(
    *,
    order_id: str,
    email_hash: str,
    settings: Settings | None = None,
) -> str:
    """Issue an order-scoped guest token that unlocks one order's delivered codes.

    Unlike :func:`mint_guest` (freely mintable from an email alone), this is minted
    only server-side and carries the specific ``order_id`` it grants access to, so
    knowing the buyer's email is not enough to read another order's codes. It rides
    the magic link in the delivered email — see ADR-0042.
    """
    s = _settings_or(settings)
    payload = _base_payload(
        sub=f"guest:{email_hash}",
        kind="guest_order",
        ttl_seconds=s.jwt_guest_order_ttl_seconds,
        settings=s,
    )
    payload["email_hash"] = email_hash
    payload["order_id"] = order_id
    return _encode(payload, settings=s)


def mint_ws_handshake(
    *,
    sub: str,
    sid: str,
    channel: str,
    settings: Settings | None = None,
) -> str:
    """Issue a 60-second token used to authorise a WebSocket ``Upgrade``."""
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub,
        kind="ws",
        ttl_seconds=s.jwt_ws_ttl_seconds,
        settings=s,
    )
    payload["sid"] = sid
    payload["channel"] = channel
    return _encode(payload, settings=s)


def mint_email_verify(
    *,
    sub: str,
    ttl_seconds: int | None = None,
    settings: Settings | None = None,
) -> str:
    """Issue a short-lived token confirming ownership of a user's email.

    Args:
        sub: The row the link confirms.
        ttl_seconds: Overrides ``jwt_email_token_ttl_seconds``. The merchant
            cabinet passes its own (``merchant_confirm_ttl_seconds``, 24 h)
            because the two are different product decisions: a storefront
            email check is confirmed in the same sitting, while a registration
            confirmation is read whenever the person next opens their work
            mail — and the copy in that mail promises a day.
        settings: Overrides the process settings; for tests.
    """
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub,
        kind="email_verify",
        ttl_seconds=s.jwt_email_token_ttl_seconds if ttl_seconds is None else ttl_seconds,
        settings=s,
    )
    return _encode(payload, settings=s)


def mint_password_reset(
    *,
    sub: str,
    settings: Settings | None = None,
) -> str:
    """Issue a short-lived, single-use (via Redis marker) password-reset token."""
    s = _settings_or(settings)
    payload = _base_payload(
        sub=sub,
        kind="password_reset",
        ttl_seconds=s.jwt_email_token_ttl_seconds,
        settings=s,
    )
    return _encode(payload, settings=s)


def verify(
    token: str,
    *,
    expected_kind: TokenKind,
    settings: Settings | None = None,
) -> Claims:
    """Decode and validate a JWT.

    Raises:
        UnauthorizedError: On signature failure, expiry, or kind mismatch.
    """
    s = _settings_or(settings)
    if not s.jwt_public_key:
        raise RuntimeError("JWT_PUBLIC_KEY is not configured — cannot verify tokens.")

    try:
        raw = jwt.decode(
            token,
            s.jwt_public_key,
            algorithms=[ALG],
            issuer=s.jwt_issuer,
            options={"require": ["iat", "exp", "iss", "sub", "jti"]},
        )
    except InvalidTokenError as exc:
        raise UnauthorizedError("invalid token") from exc

    kind = raw.get("kind")
    if kind != expected_kind:
        raise UnauthorizedError("wrong token kind")

    return Claims(
        sub=str(raw["sub"]),
        kind=cast(TokenKind, kind),
        jti=str(raw["jti"]),
        iat=datetime.fromtimestamp(int(raw["iat"]), tz=now().tzinfo),
        exp=datetime.fromtimestamp(int(raw["exp"]), tz=now().tzinfo),
        sid=raw.get("sid"),
        tg_id=raw.get("tg_id"),
        email_hash=raw.get("email_hash"),
        scope=tuple(raw.get("scope", ())),
        channel=raw.get("channel"),
        order_id=raw.get("order_id"),
    )
