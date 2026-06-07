"""Telegram bot outbound channel.

Uses the Bot API directly via httpx — we only ever *send*, never receive
updates, so pulling in aiogram's dispatcher would be overkill. A short
timeout plus swallowed errors means a Telegram outage never blocks the
caller (e.g. a payment webhook handler).
"""

from __future__ import annotations

import httpx

from yupay.core.config import get_settings
from yupay.core.logging import get_logger

log = get_logger("yupay.notifications.telegram")

# Single client reused across the API process. ``httpx.AsyncClient`` is
# cheap to instantiate but expensive to throw away (no connection pool).
_client: httpx.AsyncClient | None = None
_TIMEOUT_SECONDS = 10.0


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
) -> bool:
    """Send a single message via the Telegram Bot API.

    Returns ``True`` on success, ``False`` on any failure (network, 4xx, 5xx).
    Never raises — callers are background tasks that must not crash the loop.
    """
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    try:
        resp = await _get_client().post(url, json=payload)
    except httpx.HTTPError as exc:
        log.warning(
            "telegram.send.network_error",
            chat_id=chat_id,
            error=str(exc),
        )
        return False

    if resp.status_code == 200:
        return True

    log.warning(
        "telegram.send.rejected",
        chat_id=chat_id,
        status=resp.status_code,
        # Don't log the response body unconditionally — it can leak the message.
        # First 120 chars of Telegram's error description is enough to triage.
        body_preview=resp.text[:120],
    )
    return False
