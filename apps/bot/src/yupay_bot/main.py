"""Bot entrypoint.

Run as: ``python -m yupay_bot.main``.
"""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from sqlalchemy import text
from yupay.core.config import Settings, get_settings
from yupay.core.db import get_session_factory
from yupay.core.logging import configure_logging, get_logger

from yupay_bot.i18n import (
    miniapp_button_label,
    resolve_locale,
    welcome_message,
)

configure_logging()
log = get_logger("yupay.bot")


async def _clear_bot_blocked(tg_user_id: int) -> None:
    """Clear ``telegram_links.bot_blocked_at`` for a re-engaging Telegram user.

    The broadcast dispatch job (``yupay_scheduler.jobs.broadcast_dispatch``)
    stamps this column with ``now()`` when a send comes back 403 ("bot was
    blocked by the user") and skips that link for future broadcast audiences.
    Sending ``/start`` again is the user's signal that they've unblocked the
    bot, so we clear the flag here to make them eligible again.

    Runs in its own short-lived session/transaction, mirroring how the
    scheduler jobs touch this table — the bot has no request-scoped session
    of its own. A no-op (matches zero rows) if this Telegram id has no
    ``telegram_links`` row yet.
    """
    factory = get_session_factory()
    async with factory() as session, session.begin():
        await session.execute(
            text("UPDATE telegram_links SET bot_blocked_at = NULL WHERE tg_user_id = :tg_id"),
            {"tg_id": tg_user_id},
        )


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

        Also clears ``bot_blocked_at`` on the sender's ``telegram_links``
        row, if any — re-engaging via ``/start`` re-enables them as a
        broadcast recipient. See :func:`_clear_bot_blocked`. This is
        best-effort: the welcome is always sent first, and a DB failure
        while clearing the flag is caught and logged (no PII) rather than
        propagated — a transient DB hiccup on this brand-new dependency
        must never break `/start` itself or swallow the ``bot.start`` log.
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
        if user is not None:
            try:
                await _clear_bot_blocked(user.id)
            except Exception as exc:  # noqa: BLE001 -- a DB hiccup must never break /start
                log.warning("bot.clear_blocked_failed", error=str(exc))
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

    # Route the Bot API through an outbound proxy when configured (e.g. the host
    # cannot reach api.telegram.org directly from RU). Empty => direct connection.
    session = (
        AiohttpSession(proxy=settings.telegram_proxy_url) if settings.telegram_proxy_url else None
    )
    bot = Bot(
        token=settings.telegram_bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher(settings)
    log.info("bot.started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(run())
