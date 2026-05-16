# apps/bot — YuPay Telegram bot

aiogram 3 bot. Long-polls in dev, webhook in prod (registered via `setWebhook`
on deploy). Handlers live under `src/yupay_bot/handlers/`.

The bot is the entry point into the Telegram Mini App and the channel for fulfilment
notifications, support contact, and lightweight commands.
