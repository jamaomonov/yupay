"""Bot entrypoint.

Run as: ``python -m yupay_bot.main``.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from yupay.core.config import Settings, get_settings
from yupay.core.logging import configure_logging, get_logger

from yupay_bot.i18n import (
    miniapp_button_label,
    resolve_locale,
    welcome_message,
)

configure_logging()
log = get_logger("yupay.bot")


def build_dispatcher(settings: Settings) -> Dispatcher:
    """Build the aiogram dispatcher with all routers attached.

    Routers are added here as the bot grows.
    """
    dp = Dispatcher()

    @dp.message(Command("start"))
    async def on_start(message: Message) -> None:
        """Greet the user in their Telegram language and present the
        Mini App entry button.

        Locale comes from ``message.from_user.language_code`` — the
        IETF tag the user picked in Telegram → Settings → Language.
        Unknown / missing codes fall back to ``ru`` (UZ market default).
        """
        user = message.from_user
        locale = resolve_locale(user.language_code if user else None)
        first_name = user.first_name if user else ""

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=miniapp_button_label(locale),
                        web_app=WebAppInfo(url=settings.telegram_miniapp_url),
                    )
                ]
            ]
        )
        await message.answer(
            welcome_message(locale, first_name),
            reply_markup=keyboard,
        )
        log.info(
            "bot.start",
            user_id=user.id if user else None,
            language_code=user.language_code if user else None,
            resolved_locale=locale,
        )

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
    dp = build_dispatcher(settings)
    log.info("bot.started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run())
