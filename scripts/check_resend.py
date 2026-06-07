"""Resend deliverability check — sends a REAL email (not a unit test).

Verifies that the production ``send_email`` channel can deliver through Resend
with the configured API key + ``EMAIL_FROM``. Use it after wiring the Resend
domain to confirm DNS/verification is complete.

Usage:
    export $(grep -E '^(RESEND_API_KEY|EMAIL_FROM|EMAIL_FROM_NAME)=' .env | xargs)
    uv run python scripts/check_resend.py recipient@example.com

Exit codes: 0 sent, 1 not configured, 2 Resend rejected the send.
"""

from __future__ import annotations

import asyncio
import sys

from yupay.core.config import get_settings
from yupay.modules.notifications.channels.email import EmailSendError, send_email

_SUBJECT = "YuPay — проверка доставки (Resend)"
_HTML = (
    '<div style="font-family:system-ui,sans-serif;max-width:480px;margin:auto">'
    "<h2>YuPay</h2>"
    "<p>Это тестовое письмо для проверки канала Resend. "
    "Если вы его видите — доставка работает ✅</p>"
    '<p style="color:#888;font-size:12px;margin-top:24px">YuPay deliverability check</p></div>'
)
_TEXT = "YuPay — тестовое письмо для проверки Resend. Если вы его получили, доставка работает."


async def main(to: str) -> int:
    """Send one real test email to ``to`` via Resend; report the outcome."""
    settings = get_settings()
    if not settings.resend_api_key:
        print("RESEND_API_KEY is not configured — nothing sent.")
        return 1

    print(f"from: {settings.email_from_name} <{settings.email_from}>")
    print(f"to:   {to}")
    try:
        message_id = await send_email(to=to, subject=_SUBJECT, html=_HTML, text=_TEXT)
    except EmailSendError as exc:
        print(f"FAILED — Resend rejected the send: {exc}")
        return 2
    print(f"OK — accepted by Resend, message id: {message_id}")
    return 0


if __name__ == "__main__":
    recipient = sys.argv[1] if len(sys.argv) > 1 else ""
    if not recipient:
        print("usage: uv run python scripts/check_resend.py <recipient-email>")
        raise SystemExit(64)
    raise SystemExit(asyncio.run(main(recipient)))
