"""Which chat an admin alert lands in (owner, 2026-10-30).

Hourly digests buried the alerts someone has to act on, so ``URGENT_KINDS``
go to ``TG_URGENT_CHAT_ID`` and everything else stays in ``TG_ALERT_CHAT_ID``.
"""

from __future__ import annotations

from typing import Any

import pytest
from yupay.core.config import get_settings
from yupay.modules.notifications import alerts
from yupay.modules.notifications.channels import telegram as tg

pytestmark = pytest.mark.asyncio

MAIN, URGENT, FRAUD = "-100", "-200", "-300"


@pytest.fixture
def chats(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Configure the bot, capture the chat each message goes to."""
    settings = get_settings()
    monkeypatch.setattr(settings, "tg_alert_bot_token", "1:T")
    monkeypatch.setattr(settings, "tg_alert_chat_id", MAIN)
    monkeypatch.setattr(settings, "tg_urgent_chat_id", URGENT)
    sent: list[int] = []

    async def _send(**kwargs: Any) -> bool:  # Any: mirrors tg.send_message's kwargs
        sent.append(kwargs["chat_id"])
        return True

    monkeypatch.setattr(tg, "send_message", _send)
    return sent


async def test_an_urgent_kind_goes_to_the_urgent_chat(chats: list[int]) -> None:
    await alerts.send_admin_alert("x", kind="order_held_for_review")
    await alerts.send_admin_alert("x", kind="manual_order")
    assert chats == [int(URGENT), int(URGENT)]


async def test_a_digest_stays_in_the_main_chat(chats: list[int]) -> None:
    await alerts.send_admin_alert("x", kind="price_change")
    await alerts.send_admin_alert("x", kind="margin_drift")
    assert chats == [int(MAIN), int(MAIN)]


async def test_an_explicit_chat_wins(chats: list[int]) -> None:
    await alerts.send_admin_alert("x", kind="order_held_for_review", chat_id=FRAUD)
    assert chats == [int(FRAUD)]


async def test_no_urgent_chat_sends_everything_to_the_main_one(
    chats: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "tg_urgent_chat_id", "")
    await alerts.send_admin_alert("x", kind="fulfillment_error")
    assert chats == [int(MAIN)]
