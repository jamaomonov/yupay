"""Admin alerts — out-of-band ops notifications via a dedicated bot.

Separate from the customer-facing notifications: the admin alert bot
has its own token and chat id (env: ``TG_ALERT_BOT_TOKEN`` /
``TG_ALERT_CHAT_ID``). Keeping it on a different bot means a token leak
on the customer side can't reach the ops Telegram channel, and an
outage of one doesn't drag the other down.

Empty env vars no-op — useful in dev and on a fresh prod boot before
the alert bot is provisioned.

Two chats. Alerts someone has to act on now (``URGENT_KINDS``) go to
``TG_URGENT_CHAT_ID``; the hourly digests — price moves, margin drift,
stock — stay in ``TG_ALERT_CHAT_ID``, where they had been burying the
urgent ones (owner, 2026-10-30). An unset urgent chat sends everything to
the main one, as before.
"""

from __future__ import annotations

from yupay.core.config import get_settings
from yupay.core.logging import get_logger
from yupay.modules.notifications.channels import telegram as tg

log = get_logger("yupay.notifications.alerts")

#: Kinds that need a human soon: an order waiting on a decision or a hand,
#: money that went somewhere it should not, a supplier that cannot deliver.
#: A new ``kind`` lands in the main chat until it is added here.
URGENT_KINDS: frozenset[str] = frozenset(
    {
        "order_held_for_review",
        "order_auto_refund_escalated",
        "order_stuck",
        "manual_order",
        "fulfillment_error",
        "merchant_money_outcome",
        "merchant_order_cancelled",
        "merchant_refund_failed",
        "supplier_low_balance",
        "supplier_balance_low",
        "wallet_topup_refund_blocked",
        "paid_after_expiry",
        "skin_trade_rollback",
        "p2p_ambiguous_card",
        "p2p_order_payment_missing",
    }
)


async def send_admin_alert(
    text: str, *, kind: str = "unspecified", chat_id: str | None = None
) -> bool:
    """Fire-and-forget message to the ops admin chat.

    Returns ``True`` on a successful Telegram delivery, ``False`` when
    the bot isn't configured or the upstream rejected the call. Never
    raises — callers are usually scheduler jobs that must not crash.

    Every outcome is logged at INFO, including success. That is not noise:
    without it, "no alert arrived" is indistinguishable from "no alert was
    ever sent", and after an incident there is no way to tell which. The
    unconfigured branch used to log at DEBUG, which prod (LOG_LEVEL=INFO)
    silently discarded — the one case where silence was most misleading.

    ``kind`` is a short label for the alert type so the log can be filtered
    per alert rather than per line, and it picks the chat: an ``URGENT_KINDS``
    kind goes to the urgent chat when one is set. An explicit ``chat_id``
    wins over both.
    """
    settings = get_settings()
    token = settings.tg_alert_bot_token
    urgent = settings.tg_urgent_chat_id if kind in URGENT_KINDS else ""
    chat_id_raw = chat_id or urgent or settings.tg_alert_chat_id
    if not token or not chat_id_raw:
        log.warning("alerts.not_configured", kind=kind)
        return False
    try:
        chat_id_int = int(chat_id_raw.strip())
    except ValueError:
        log.warning("alerts.invalid_chat_id", kind=kind)
        return False
    delivered = await tg.send_message(
        bot_token=token,
        chat_id=chat_id_int,
        text=text,
        parse_mode="HTML",
    )
    if delivered:
        log.info("alerts.delivered", kind=kind)
    else:
        log.warning("alerts.delivery_failed", kind=kind)
    return delivered


__all__ = ["URGENT_KINDS", "send_admin_alert"]
