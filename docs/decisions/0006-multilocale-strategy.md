# 0006. Locale strategy (RU default, EN, UZ latin)

- **Status**: Accepted (Mini App runtime/transport superseded by ADR-0022)
- **Date**: 2026-05-15
- **Deciders**: founding team
- **Tags**: frontend, i18n

## Context

YuPay launches in three locales: Russian (primary CIS market), English (international),
Uzbek Latin (home market). The web storefront is SEO-driven; the Mini App is not indexed
but inherits the same content.

## Decision

- Library: **`next-intl` v4** in both Next.js apps.
- Locale routing on web: `localePrefix: "as-needed"` — Russian URLs are bare
  (`/games/steam`), English and Uzbek are prefixed (`/en/games/steam`, `/uz/games/steam`).
- Locale routing on Mini App: not URL-based. Detected from
  `Telegram.WebApp.initDataUnsafe.user.language_code` mapped to `ru` / `en` / `uz` (default
  `ru` on unknown). **(Superseded by ADR-0022:** the Mini App moved to Vite (ADR-0016)
  with a custom runtime, a Settings language switcher, and a DB-persisted
  `users.locale` that now takes precedence over `language_code`.**)**
- **Single source of truth** for message catalogues: `packages/i18n/locales/{ru,en,uz}/<namespace>.json`,
  consumed by both apps.
- **All three locales updated in the same PR** — CI fails if any key is missing from any
  locale.
- Plurals via ICU MessageFormat (next-intl supports it).
- Currency, dates, numbers formatted via `Intl.*`; never string-concatenated.
- SEO: `hreflang` tags emitted per page; canonical URLs include the locale.

## Consequences

- A missing translation breaks the build — friction that pays for itself in launch quality.
- Web's default locale (`ru`) ships bare URLs, maximising existing SEO value on the home
  market.
- Adding a fourth locale (Uzbek Cyrillic, Kazakh, etc.) is a folder + a config entry.

## Alternatives considered

- **`react-i18next`** — battle-tested, but App Router integration is rougher than
  next-intl's RSC-native flow.
- **Per-app catalogues** — rejected: drift between web and Mini App is the most common
  i18n bug.

## References

- [next-intl docs](https://next-intl-docs.vercel.app/)
