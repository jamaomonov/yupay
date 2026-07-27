"""Contract tests for ``send_message`` (respx-mocked).

Focused on the PII-in-logs fix: ``chat_id`` is a Telegram user identifier and
must never be passed as a structured-log field from ``send_message``'s
failure paths — mirroring ``send_broadcast_message``, which already omits it.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from yupay.modules.notifications.channels import telegram as tg

BOT_TOKEN = "123456:TEST-TOKEN"
CHAT_ID = 555000111
_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"


@respx.mock
async def test_send_message_success_returns_true() -> None:
    respx.post(f"{_BASE}/sendMessage").mock(return_value=httpx.Response(200, json={"ok": True}))
    ok = await tg.send_message(bot_token=BOT_TOKEN, chat_id=CHAT_ID, text="hi")
    assert ok is True


@respx.mock
async def test_send_message_rejected_does_not_log_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    respx.post(f"{_BASE}/sendMessage").mock(
        return_value=httpx.Response(403, text="Forbidden: bot was blocked by the user")
    )
    captured: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(tg.log, "warning", lambda event, **kw: captured.append((event, kw)))

    ok = await tg.send_message(bot_token=BOT_TOKEN, chat_id=CHAT_ID, text="hi")

    assert ok is False
    assert len(captured) == 1
    event, fields = captured[0]
    assert event == "telegram.send.rejected"
    assert "chat_id" not in fields
    assert str(CHAT_ID) not in repr(fields)


@respx.mock
async def test_send_message_network_error_does_not_log_chat_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    respx.post(f"{_BASE}/sendMessage").mock(side_effect=httpx.ConnectError("boom"))
    captured: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(tg.log, "warning", lambda event, **kw: captured.append((event, kw)))

    ok = await tg.send_message(bot_token=BOT_TOKEN, chat_id=CHAT_ID, text="hi")

    assert ok is False
    assert len(captured) == 1
    event, fields = captured[0]
    assert event == "telegram.send.network_error"
    assert "chat_id" not in fields
    assert str(CHAT_ID) not in repr(fields)
