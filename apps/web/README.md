# @yupay/web — public storefront

Next.js 15 (App Router, RSC). SEO-driven, guest-friendly checkout.

- Locale routing: `/[locale]/...` with `localePrefix: "as-needed"` (`ru` is bare, `en`/`uz`
  are prefixed).
- Rendering: SSG for catalog/product pages, ISR for landing, SSR for checkout/account.
- Server Components by default; `"use client"` only when necessary.
- API client: `@yupay/api-client` (generated from FastAPI's OpenAPI 3.1 schema).
- Design system: `@yupay/ui` + `@yupay/config-tailwind`.

```bash
make dev-web   # foreground, requires the API to be reachable
```

## Environment

| Variable                            | Description                                                                                                                                                                                                                                |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `NEXT_PUBLIC_API_BASE_URL`          | Base URL of the FastAPI backend (e.g. `https://api.yupay.uz`). Inlined at build time.                                                                                                                                                      |
| `NEXT_PUBLIC_TELEGRAM_BOT_USERNAME` | Telegram bot username (without `@`) used to render the Telegram Login Widget. Inlined at build time.                                                                                                                                       |
| `NEXT_PUBLIC_TELEGRAM_BOT_ID`       | The bot's numeric id (the token prefix before `:`), used to trigger the Telegram OAuth popup from the login modal's custom button. When empty, the modal renders the official Telegram widget button as a fallback. Inlined at build time. |
| `NEXT_PUBLIC_SENTRY_DSN`            | Sentry DSN for client-side error reporting. Leave empty to disable.                                                                                                                                                                        |
| `NEXT_PUBLIC_PLAUSIBLE_DOMAIN`      | Domain registered in Plausible Analytics. Leave empty to disable analytics.                                                                                                                                                                |
