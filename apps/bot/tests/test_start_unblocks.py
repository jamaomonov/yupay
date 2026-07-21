"""Wiring test: the ``/start`` handler clears ``bot_blocked_at`` for its sender.

The actual DB update (``_clear_bot_blocked``) needs a real Postgres — that is
covered by an integration test in
``apps/api/tests/integration/test_bot_start_unblocks.py`` (mirrors how
scheduler-job DB logic that lives outside ``apps/api`` is already tested
there, e.g. ``test_broadcast_dispatch.py``; ``apps/bot/tests`` has no
testcontainers fixture of its own). Here we only verify that ``on_start``
invokes ``_clear_bot_blocked`` with the sender's Telegram id — the wiring
this task adds — without touching a database at all.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from yupay.core.config import Settings
from yupay_bot import main as bot_main

pytestmark = pytest.mark.asyncio


def _start_handler() -> Any:
    """Pull the registered ``/start`` callback out of the dispatcher.

    ``on_start`` is a nested closure inside ``build_dispatcher`` (it closes
    over ``settings``), so there is no module-level name to import directly.
    aiogram stores the raw callback on ``HandlerObject.callback`` (see
    ``aiogram.dispatcher.event.handler.CallableObject``), so pulling it off
    the single registered handler is equivalent to calling ``on_start``
    itself.
    """
    dp = bot_main.build_dispatcher(Settings())
    return dp.message.handlers[0].callback


async def test_start_clears_bot_blocked_at_for_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    clear_mock = AsyncMock()
    monkeypatch.setattr(bot_main, "_clear_bot_blocked", clear_mock)

    handler = _start_handler()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=987654321, language_code="ru", first_name="Жанна"),
        answer=AsyncMock(),
    )

    await handler(message)

    clear_mock.assert_awaited_once_with(987654321)


async def test_start_without_from_user_skips_db_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anonymous/channel senders have no ``from_user`` — must not crash or
    call the clear helper with a nonsensical id."""
    clear_mock = AsyncMock()
    monkeypatch.setattr(bot_main, "_clear_bot_blocked", clear_mock)

    handler = _start_handler()
    message = SimpleNamespace(from_user=None, answer=AsyncMock())

    await handler(message)

    clear_mock.assert_not_awaited()
