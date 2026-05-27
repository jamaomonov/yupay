"""Admin alerts — out-of-band ops notifications via a dedicated bot.

Separate from the customer-facing notifications: the admin alert bot
has its own token and chat id (env: ``TG_ALERT_BOT_TOKEN`` /
``TG_ALERT_CHAT_ID``). Keeping it on a different bot means a token leak
on the customer side can't reach the ops Telegram channel, and an
outage of one doesn't drag the other down.

Empty env vars no-op — useful in dev and on a fresh prod boot before
the alert bot is provisioned.
"""

from __future__ import annotations

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.notifications.channels import telegram as tg

log = get_logger("yupay.notifications.alerts")


async def send_admin_alert(text: str) -> bool:
    """Fire-and-forget message to the ops admin chat.

    Returns ``True`` on a successful Telegram delivery, ``False`` when
    the bot isn't configured or the upstream rejected the call. Never
    raises — callers are usually scheduler jobs that must not crash.
    """
    settings = get_settings()
    token = settings.tg_alert_bot_token
    chat_id_raw = settings.tg_alert_chat_id
    if not token or not chat_id_raw:
        log.debug("alerts.skip", reason="not configured")
        return False
    try:
        chat_id = int(chat_id_raw.strip())
    except ValueError:
        log.warning("alerts.invalid_chat_id", value=chat_id_raw)
        return False
    return await tg.send_message(
        bot_token=token,
        chat_id=chat_id,
        text=text,
        parse_mode="HTML",
    )


__all__ = ["send_admin_alert"]
