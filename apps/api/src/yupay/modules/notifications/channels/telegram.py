"""Telegram bot outbound channel.

Uses the Bot API directly via httpx — we only ever *send*, never receive
updates, so pulling in aiogram's dispatcher would be overkill. A short
timeout plus swallowed errors means a Telegram outage never blocks the
caller (e.g. a payment webhook handler).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from yupay.core.config import get_settings
from yupay.core.logging import get_logger

log = get_logger("yupay.notifications.telegram")

# Single client reused across the API process. ``httpx.AsyncClient`` is
# cheap to instantiate but expensive to throw away (no connection pool).
_client: httpx.AsyncClient | None = None
_TIMEOUT_SECONDS = 10.0

# Telegram Bot API method for each broadcast media type.
_METHOD_BY_MEDIA_TYPE = {
    "none": "sendMessage",
    "photo": "sendPhoto",
    "video": "sendVideo",
    "animation": "sendAnimation",
    "document": "sendDocument",
}

# Payload field that carries the media URL/file_id, per media type ("none" has
# no media field — it sends "text" instead, handled separately).
_MEDIA_FIELD_BY_MEDIA_TYPE = {
    "photo": "photo",
    "video": "video",
    "animation": "animation",
    "document": "document",
}

# Truncate Telegram's error description before it's stored/returned, so a
# verbose upstream message can never blow up a recipient row or a log line.
_DESCRIPTION_MAX_LEN = 200


@dataclass(frozen=True, slots=True)
class SendOutcome:
    """Result of one ``send_broadcast_message`` call.

    Attributes:
        ok: Whether Telegram accepted the send (HTTP 200).
        file_id: Telegram's own id for the media just sent, captured from the
            response so later sends can reuse it instead of re-uploading.
            Always ``None`` for text-only sends.
        status: HTTP status code Telegram returned, or ``0`` on a network
            error (connection failure, timeout, etc.).
        retry_after: Seconds to wait before retrying, from a 429 response.
        description: Telegram's error description, truncated. Empty on success.
    """

    ok: bool
    file_id: str | None = None
    status: int = 0
    retry_after: int | None = None
    description: str = ""


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # Route through an outbound proxy when configured (e.g. the host cannot
        # reach api.telegram.org directly from RU). Empty => direct connection.
        proxy = get_settings().telegram_proxy_url or None
        _client = httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, proxy=proxy)
    return _client


async def send_message(
    *,
    bot_token: str,
    chat_id: int,
    text: str,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = True,
    reply_markup: dict[str, Any] | None = None,
) -> bool:
    """Send a single message via the Telegram Bot API.

    Returns ``True`` on success, ``False`` on any failure (network, 4xx, 5xx).
    Never raises — callers are background tasks that must not crash the loop.
    ``reply_markup`` is forwarded as-is (inline keyboard / web_app button).
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    try:
        resp = await _get_client().post(url, json=payload)
    except httpx.HTTPError as exc:
        # No chat_id here — a chat id is a Telegram user identifier (PII) and
        # is not on the structured-logger redaction blocklist.
        log.warning(
            "telegram.send.network_error",
            error=str(exc),
        )
        return False

    if resp.status_code == 200:
        return True

    log.warning(
        "telegram.send.rejected",
        status=resp.status_code,
        # Don't log the response body unconditionally — it can leak the message.
        # First 120 chars of Telegram's error description is enough to triage.
        body_preview=resp.text[:120],
    )
    return False


def _extract_file_id(media_type: str, result: dict[str, Any]) -> str | None:
    """Pull the Telegram ``file_id`` for ``media_type`` out of a success ``result``.

    Telegram nests it differently per method: ``sendPhoto`` returns a list of
    sizes (we want the largest, i.e. the last one); the others return a single
    object. Any unexpected shape (missing key, wrong type) is treated as "no
    file_id captured" rather than an error — the send itself still succeeded.
    """
    if media_type == "photo":
        photos = result.get("photo")
        if isinstance(photos, list) and photos:
            last = photos[-1]
            if isinstance(last, dict):
                file_id = last.get("file_id")
                if isinstance(file_id, str):
                    return file_id
        return None

    media = result.get(media_type)
    if isinstance(media, dict):
        file_id = media.get("file_id")
        if isinstance(file_id, str):
            return file_id
    return None


async def send_broadcast_message(
    *,
    bot_token: str,
    chat_id: int,
    body_html: str,
    media_type: str,
    media_url_or_file_id: str | None,
    disable_web_page_preview: bool = True,
) -> SendOutcome:
    """Send one broadcast message (text-only or with one media attachment).

    This is the single entry point the scheduler dispatch job and the admin
    test-send route use. Unlike :func:`send_message`, it captures the
    Telegram ``file_id`` assigned to freshly-uploaded media so the caller can
    persist it and resend by ``file_id`` (no re-upload) for the rest of the
    broadcast.

    Args:
        bot_token: The bot token to send with.
        chat_id: Destination chat id.
        body_html: Telegram-HTML text (media_type "none") or caption
            (any other media_type). Caller is responsible for whitelist
            validation before this call.
        media_type: One of "none", "photo", "video", "animation", "document".
        media_url_or_file_id: A public URL on the first send for a given
            broadcast, or a previously-captured Telegram ``file_id`` on
            subsequent sends. Ignored when ``media_type`` is "none".
        disable_web_page_preview: Only meaningful for "none" (plain-text) sends.

    Returns:
        A `SendOutcome`. Never raises — callers are background dispatch jobs
        and an admin-triggered test-send, neither of which may crash on a
        single failed delivery.
    """
    method = _METHOD_BY_MEDIA_TYPE.get(media_type)
    if method is None:
        return SendOutcome(ok=False, description=f"unknown media_type: {media_type}")

    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    payload: dict[str, Any]
    if media_type == "none":
        payload = {
            "chat_id": chat_id,
            "text": body_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview,
        }
    else:
        payload = {
            "chat_id": chat_id,
            _MEDIA_FIELD_BY_MEDIA_TYPE[media_type]: media_url_or_file_id,
            "caption": body_html,
            "parse_mode": "HTML",
        }

    try:
        resp = await _get_client().post(url, json=payload)
    except httpx.HTTPError as exc:
        # No chat_id/body here — a chat id is a Telegram user identifier (PII)
        # and is not on the structured-logger redaction blocklist.
        log.warning("telegram.broadcast.network_error", media_type=media_type, error=str(exc))
        return SendOutcome(ok=False, status=0, description=str(exc)[:_DESCRIPTION_MAX_LEN])

    body: dict[str, Any] = {}
    try:
        parsed = resp.json()
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        body = parsed

    if resp.status_code == 200:
        result = body.get("result")
        file_id = (
            _extract_file_id(media_type, result)
            if media_type != "none" and isinstance(result, dict)
            else None
        )
        return SendOutcome(ok=True, file_id=file_id, status=200)

    description = ""
    raw_description = body.get("description")
    if isinstance(raw_description, str):
        description = raw_description[:_DESCRIPTION_MAX_LEN]

    retry_after: int | None = None
    parameters = body.get("parameters")
    if isinstance(parameters, dict):
        raw_retry_after = parameters.get("retry_after")
        if isinstance(raw_retry_after, int):
            retry_after = raw_retry_after

    log.warning(
        "telegram.broadcast.rejected",
        media_type=media_type,
        status=resp.status_code,
        retry_after=retry_after,
    )
    return SendOutcome(
        ok=False,
        status=resp.status_code,
        retry_after=retry_after,
        description=description,
    )
