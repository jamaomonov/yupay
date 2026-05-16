"""Bot entrypoint.

Run as: ``python -m yupay_bot.main``.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message
from yupay.core.config import get_settings
from yupay.core.logging import configure_logging, get_logger

configure_logging()
log = get_logger("yupay.bot")


def build_dispatcher() -> Dispatcher:
    """Build the aiogram dispatcher with all routers attached.

    Routers are added here as the bot grows.
    """
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def on_start(message: Message) -> None:
        """Greet the user and present the Mini App entry button."""
        await message.answer("YuPay — coming soon.")

    return dp


async def run() -> None:
    """Start long-polling against the configured bot token."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        log.warning("bot.no_token; sleeping")
        await asyncio.sleep(3600)
        return

    bot = Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()
    log.info("bot.started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run())
