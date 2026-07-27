"""Telegram signature verification.

Implements two related but distinct algorithms:

- :func:`verify_init_data` — Telegram Mini App initData (HMAC key = ``HMAC-SHA256(
  "WebAppData", bot_token)``). Reference: https://core.telegram.org/bots/webapps
- :func:`verify_login_widget` — Telegram Login Widget (HMAC key = ``SHA256(bot_token)``).
  Reference: https://core.telegram.org/widgets/login#checking-authorization

Both functions return a typed payload on success and raise
:class:`TelegramAuthError` on any verification failure (bad signature, missing field,
stale ``auth_date``). The caller is responsible for upserting users.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Final
from urllib.parse import parse_qsl

from yupay.core.clock import now
from yupay.core.redis import get_redis


class TelegramAuthError(Exception):
    """Raised when Telegram-supplied data fails verification."""


# Maximum tolerated clock skew between Telegram's auth_date and our wall clock.
_CLOCK_SKEW_TOLERANCE_SECONDS = 60


@dataclass(frozen=True)
class TelegramUser:
    """A verified Telegram identity. Mirrors the subset of fields we persist."""

    id: int
    first_name: str | None
    last_name: str | None
    username: str | None
    language_code: str | None
    is_premium: bool
    photo_url: str | None


@dataclass(frozen=True)
class VerifiedInitData:
    """Result of a successful :func:`verify_init_data` call."""

    user: TelegramUser
    auth_date: int
    query_id: str | None
    start_param: str | None
    raw: str


@dataclass(frozen=True)
class VerifiedLoginWidget:
    """Result of a successful :func:`verify_login_widget` call."""

    user: TelegramUser
    auth_date: int
    hash: str


_HASH_FIELD: Final[str] = "hash"


def _data_check_string(fields: dict[str, str]) -> bytes:
    """Build the ``key=value\\n``-joined check string per Telegram spec.

    Pairs are sorted alphabetically by key. The ``hash`` field is excluded.
    """
    pairs = sorted((k, v) for k, v in fields.items() if k != _HASH_FIELD)
    return "\n".join(f"{k}={v}" for k, v in pairs).encode("utf-8")


def _parse_user(blob: str) -> TelegramUser:
    payload = json.loads(blob)
    return TelegramUser(
        id=int(payload["id"]),
        first_name=payload.get("first_name"),
        last_name=payload.get("last_name"),
        username=payload.get("username"),
        language_code=payload.get("language_code"),
        is_premium=bool(payload.get("is_premium", False)),
        photo_url=payload.get("photo_url"),
    )


def verify_init_data(init_data: str, *, bot_token: str, max_age_seconds: int) -> VerifiedInitData:
    """Verify the ``initData`` string supplied by a Telegram Mini App.

    Args:
        init_data: Raw query-string-like payload from ``Telegram.WebApp.initData``.
        bot_token: The bot token (kept server-side).
        max_age_seconds: Reject payloads older than this many seconds.

    Returns:
        A :class:`VerifiedInitData` with the parsed user.

    Raises:
        TelegramAuthError: If signature, structure, or freshness checks fail.
    """
    if not init_data:
        raise TelegramAuthError("empty initData")

    fields = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    provided_hash = fields.get(_HASH_FIELD)
    if not provided_hash:
        raise TelegramAuthError("missing hash")

    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, _data_check_string(fields), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, provided_hash):
        raise TelegramAuthError("hash mismatch")

    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError as exc:
        raise TelegramAuthError("invalid auth_date") from exc

    if auth_date <= 0:
        raise TelegramAuthError("invalid auth_date")

    age = int(now().timestamp()) - auth_date
    if age > max_age_seconds:
        raise TelegramAuthError("initData expired")
    if age < -_CLOCK_SKEW_TOLERANCE_SECONDS:
        raise TelegramAuthError("initData from the future")

    user_blob = fields.get("user")
    if not user_blob:
        raise TelegramAuthError("missing user field")

    try:
        user = _parse_user(user_blob)
    except (KeyError, ValueError, TypeError) as exc:
        raise TelegramAuthError("malformed user payload") from exc

    return VerifiedInitData(
        user=user,
        auth_date=auth_date,
        query_id=fields.get("query_id"),
        start_param=fields.get("start_param"),
        raw=init_data,
    )


def verify_login_widget(
    payload: dict[str, str | int | bool],
    *,
    bot_token: str,
    max_age_seconds: int,
) -> VerifiedLoginWidget:
    """Verify a Telegram Login Widget payload received by the public web.

    Args:
        payload: The JSON object posted by the widget (``id``, ``first_name``, ...,
            ``auth_date``, ``hash``).
        bot_token: The bot token (server-side).
        max_age_seconds: Reject payloads older than this many seconds.

    Returns:
        A :class:`VerifiedLoginWidget` with the parsed user.

    Raises:
        TelegramAuthError: If signature, structure, or freshness checks fail.
    """
    if not payload:
        raise TelegramAuthError("empty payload")

    # Stringify everything per spec; booleans become "true"/"false".
    fields: dict[str, str] = {
        k: ("true" if v is True else "false" if v is False else str(v))
        for k, v in payload.items()
        if v is not None
    }

    provided_hash = fields.get(_HASH_FIELD)
    if not provided_hash:
        raise TelegramAuthError("missing hash")

    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(secret_key, _data_check_string(fields), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected_hash, provided_hash):
        raise TelegramAuthError("hash mismatch")

    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError as exc:
        raise TelegramAuthError("invalid auth_date") from exc

    if auth_date <= 0:
        raise TelegramAuthError("invalid auth_date")

    age = int(now().timestamp()) - auth_date
    if age > max_age_seconds:
        raise TelegramAuthError("login payload expired")
    if age < -_CLOCK_SKEW_TOLERANCE_SECONDS:
        raise TelegramAuthError("login payload from the future")

    try:
        tg_id = int(fields["id"])
    except (KeyError, ValueError) as exc:
        raise TelegramAuthError("missing or invalid id") from exc

    user = TelegramUser(
        id=tg_id,
        first_name=fields.get("first_name"),
        last_name=fields.get("last_name"),
        username=fields.get("username"),
        language_code=None,
        is_premium=False,
        photo_url=fields.get("photo_url"),
    )
    return VerifiedLoginWidget(user=user, auth_date=auth_date, hash=provided_hash)


async def enforce_widget_single_use(
    *,
    widget_hash: str,
    auth_date: int,
    max_age_seconds: int,
) -> None:
    """Reject a replayed Login Widget signature (single-use within its freshness window).

    The HMAC + ``auth_date`` freshness checks in :func:`verify_login_widget` prove the
    payload is authentic and recent, but not that it is *fresh* — an attacker who
    captures a valid widget response can replay it until ``auth_date`` ages out. This
    burns the signature on first use via a Redis ``SET NX`` marker, mirroring the
    ``auth:pwreset:{jti}`` single-use pattern. The marker TTL equals the remaining
    freshness window, so it expires exactly when a replay would be rejected on age.

    Args:
        widget_hash: The verified widget ``hash`` (its HMAC signature).
        auth_date: The widget's ``auth_date`` (unix seconds).
        max_age_seconds: The freshness window the caller enforces.

    Raises:
        TelegramAuthError: If this signature has already been consumed.
    """
    ttl = max_age_seconds - (int(now().timestamp()) - auth_date)
    if ttl <= 0:
        # Already stale — the freshness check will have rejected it; nothing to burn.
        return
    key = f"auth:tg-widget:{hashlib.sha256(widget_hash.encode('utf-8')).hexdigest()}"
    was_set = await get_redis().set(key, "1", ex=ttl, nx=True)
    if not was_set:
        raise TelegramAuthError("login payload already used")
