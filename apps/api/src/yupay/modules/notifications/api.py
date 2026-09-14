"""Public interface for the ``notifications`` module.

Other modules import only the names re-exported here — never reach into
``service`` or ``channels`` directly.
"""

from __future__ import annotations

from yupay.modules.notifications.alerts import send_admin_alert
from yupay.modules.notifications.service import (
    notify_order_delivered,
    notify_order_failed,
    notify_order_paid,
    notify_review_reminder,
    schedule,
    schedule_after_commit,
)

__all__ = [
    "notify_order_delivered",
    "notify_order_failed",
    "notify_order_paid",
    "notify_review_reminder",
    "schedule",
    "schedule_after_commit",
    "send_admin_alert",
]
