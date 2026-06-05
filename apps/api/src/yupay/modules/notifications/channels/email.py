"""Transactional email via Resend (https://resend.com).

A thin async wrapper over the Resend REST API. Only the ``send`` capability is
used; the client is created per call (cheap) so configuration changes are picked
up without a process restart. PII (the recipient address) is never logged.
"""

from __future__ import annotations

import httpx

from yupay.core.config import get_settings

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT = httpx.Timeout(10.0)


class EmailSendError(RuntimeError):
    """Raised when Resend rejects a send (non-2xx) or the call cannot complete."""


async def send_email(*, to: str, subject: str, html: str, text: str) -> str:
    """Send one transactional email through Resend.

    Args:
        to: Recipient address.
        subject: Subject line.
        html: HTML body.
        text: Plain-text fallback body.

    Returns:
        The Resend message id.

    Raises:
        EmailSendError: When the API key is missing or Resend returns non-2xx.
    """
    settings = get_settings()
    if not settings.resend_api_key:
        raise EmailSendError("RESEND_API_KEY is not configured")

    payload = {
        "from": f"{settings.email_from_name} <{settings.email_from}>",
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    headers = {"Authorization": f"Bearer {settings.resend_api_key}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(_RESEND_URL, json=payload, headers=headers)
    except httpx.HTTPError as exc:  # network/timeout
        raise EmailSendError("resend request failed") from exc

    if resp.status_code >= 300:
        raise EmailSendError(f"resend returned {resp.status_code}")
    return str(resp.json().get("id", ""))


__all__ = ["EmailSendError", "send_email"]
