# @yupay/i18n

Single source of truth for translations. Three locales: `ru` (default), `en`, `uz`. Every
key must exist in all three locale files; CI will fail otherwise.

Files are organised by feature namespace: `locales/<locale>/<namespace>.json`.

Consumers (`apps/web`, `apps/miniapp`) configure `next-intl` to read from `@yupay/i18n/locales/...`.
