# 0022. Mini App runtime i18n and user-selectable, DB-persisted locale

- **Status**: Accepted
- **Date**: 2026-05-30
- **Deciders**: @jamaomonov
- **Tags**: frontend | i18n | miniapp

## Context and problem statement

ADR-0006 chose **`next-intl`** for "both Next.js apps" and specified that the
Mini App derives its locale solely from
`Telegram.WebApp.initDataUnsafe.user.language_code`. Two facts have since
invalidated that for the Mini App:

1. **The Mini App is no longer Next.js.** ADR-0016 moved it to a Vite + React 19
   SPA, so `next-intl` (RSC-native, App-Router-coupled) does not apply.
2. **Locale must be user-selectable and durable.** Telegram's `language_code`
   is a one-time hint, not a preference — a Russian-speaking user on an English
   phone had no way to switch, and any choice was lost on the next launch and
   never reached server-rendered content (emails, bot messages).

We need an i18n runtime that fits a Vite SPA, lets the user pick a language, and
persists that choice server-side next to `display_currency`.

## Decision

- **Custom lightweight runtime** in `apps/miniapp/src/lib/i18n` instead of
  pulling a full i18n framework into the 120 KB-budgeted bundle:
  - Flat, dot-namespaced JSON catalogs (the same
    `packages/i18n/locales/{ru,en,uz}/miniapp.json` source of truth from
    ADR-0006 — **no per-app drift**).
  - `t(key, params?)` for strings, `tn(key, count, params?)` for plurals.
    Plurals use **`Intl.PluralRules`** (CLDR `one/few/many/other`); every plural
    object carries all four categories in every locale for type parity.
  - `{name}` interpolation via a small regex.
  - `useT()` / `useLocale()` hooks for components; `translate` /
    `translatePlural` / `getActiveLocale` from `@/lib/i18n/core` for
    module-level code (label maps, helpers) that runs outside React.
  - Type safety: `Catalog = typeof ruMessages`; `MessageKey` is the set of
    string-valued keys and `PluralKey` the object-valued keys, so an unknown key
    is a compile error.
- **Locale resolution order**: persisted `users.locale` (from `/auth/me`) →
  Telegram `language_code` → `ru`.
- **User-selectable**: a language switcher in Settings writes the choice through
  `PATCH /api/v1/users/me { locale }`, optimistically patching the `/auth/me`
  cache so the UI flips in the same frame.
- **Server is the source of truth**: `users.locale` is tightened to
  `Literal["ru","en","uz"]` (`UpdateMeIn`), mirrored by a service-layer
  allow-list for non-HTTP callers. Unsupported locales are rejected (422).
- **Dates/numbers** are formatted via `Intl.*` keyed by the active locale
  (replacing previously hard-coded `ru` / `ru-RU`), per ADR-0006.
- **Key parity retained**: all three locales updated in the same PR.

## Consequences

- Tiny runtime, no framework weight, fits the Mini App bundle budget.
- One catalog source still shared with the web app; web keeps `next-intl`.
- A user's language now follows them across devices and into any future
  server-rendered surface that reads `users.locale`.
- The service-layer locale allow-list is belt-and-suspenders: with the `Literal`
  schema in place it is unreachable via HTTP, but keeps `update_me` safe for
  direct callers.
- Adding a fourth locale is still "a folder + a config entry", plus one entry in
  `LOCALES`.

## Alternatives considered

- **`next-intl` / `react-i18next`** in the Mini App — rejected: framework weight
  against a 120 KB budget for a feature this small; `next-intl` is App-Router
  coupled.
- **Locale in `localStorage` only** — rejected: drifts between devices and never
  reaches server-rendered content; this is exactly the failure `display_currency`
  already moved away from.

## References

- ADR-0006 (locale strategy — superseded for the Mini App runtime/transport;
  catalog source-of-truth and key-parity rules still hold)
- ADR-0016 (Mini App Vite stack)
