# Design: Web login modal (multi-provider)

**Date:** 2026-06-07
**Status:** Approved (brainstorming) — pending implementation plan
**Surface:** Public web storefront (`apps/web`) only
**Branch:** `main` (per user instruction)

---

## 1. Problem

The web `/login` is a plain page with an email/password form plus the Telegram Login
Widget's own (un-styled) button. The desired UX is a polished **modal** — "Войдите или
зарегистрируйтесь" — opened from the header and at the `/login` route, offering a grid of
sign-in providers (Telegram, Google, Steam, Email).

## 2. Goals / Non-goals

**Goals**
- A reusable **login modal** opened from the header "Войти" and rendered at `/login`.
- Provider grid (2×2): **Telegram** and **Email** functional; **Google** and **Steam** shown
  with a "скоро" badge (disabled — backend OAuth/OpenID not built yet).
- Email opens a second screen with the existing email/password form (register/forgot links).
- Accessible dialog: `role="dialog"`, `aria-modal`, Esc + backdrop close, focus management.
- All three locales (ru/en/uz) for new strings.

**Non-goals (deferred / out)**
- Google OAuth 2.0 and Steam OpenID **backend** — a later slice; the buttons are inert now.
- VK / Yandex / Facebook providers (present in the reference mockup, not requested).
- Promo-code field (explicitly dropped).
- Left-panel mascot image (single-column modal).

## 3. Decisions (locked during brainstorming)

- **Providers shown:** Telegram, Google, Steam, Email. Google/Steam are **"скоро"** (inert).
- **Open mechanism:** a **Zustand store** `useLoginModal` (`isOpen/open/close`); the modal is
  mounted once in the locale layout and overlays any page. Header and `/login` call `open()`.
- **No image:** single-column modal (provider grid only).
- **Telegram button:** a custom-styled button triggers the Telegram OAuth popup
  `window.Telegram.Login.auth({ bot_id, request_access: 'write' }, cb)` →
  `loginWithTelegram(user)`. Needs the numeric **bot id** via `NEXT_PUBLIC_TELEGRAM_BOT_ID`
  (the token prefix before `:`). When the id is absent, fall back to the official widget button
  (`TelegramLoginButton`) so Telegram login still works.
- **Email:** reuses `AuthForm` (a new `showTelegram?: boolean` prop hides its inline Telegram
  button inside the modal).

## 4. Components (`apps/web/src/components/auth/`)

- `LoginModal.tsx` — the dialog. Two screens: (a) provider grid (default) and (b) the email
  form. Backdrop (`fixed inset-0` dark blur), centered card (dark `bg-card`, rounded), title,
  2×2 button grid, "назад" on the email screen, footer with Privacy/Terms links, close (×).
  Esc + backdrop click + × all call `close()`. Autofocus the first actionable control; restore
  focus to the opener on close. Renders `null` when `!isOpen`.
- `ProviderButton.tsx` — a styled button: `{ icon, label, onClick?, soon?, variant }`. `soon`
  renders a small "скоро" badge and sets `disabled` + `aria-disabled`. Variants give each
  provider its accent (Telegram blue, Google white, Steam slate, Email neutral) consistent with
  the dark theme tokens.
- `ProviderIcons.tsx` — compact inline-SVG brand glyphs for Telegram / Google / Steam; Email
  uses lucide `Mail`.
- `useLoginModal.ts` — Zustand store: `isOpen: boolean`, `open()`, `close()`.

## 5. Integration

- `components/auth/AccountMenu.tsx` — the unauthenticated "Войти" becomes a `<button>` calling
  `useLoginModal().open()` (instead of a `<Link href=/login>`). Authenticated menu unchanged.
- `app/[locale]/login/page.tsx` — on mount calls `open()`; renders nothing else (the modal owns
  the backdrop). Close (×/Esc/backdrop) routes to `/${locale}`. Keeps the `/login` URL working
  for direct links and the `/account` auth-gate redirect.
- `app/[locale]/layout.tsx` — mount `<LoginModal />` once inside `<Providers>` so it overlays
  every route.
- `components/auth/AuthForm.tsx` — add `showTelegram?: boolean` (default `true`); the modal's
  email screen passes `false`.

## 6. Telegram popup detail

The widget script (`https://telegram.org/js/telegram-widget.js?22`) exposes
`window.Telegram.Login.auth({ bot_id, request_access }, callback)`. The Telegram button:
1. Ensures the script is loaded (inject once, idempotent).
2. On click, calls `Telegram.Login.auth({ bot_id: Number(NEXT_PUBLIC_TELEGRAM_BOT_ID),
   request_access: 'write' }, (user) => user && void loginWithTelegram(user))`.
3. If `NEXT_PUBLIC_TELEGRAM_BOT_ID` is unset, render the existing `TelegramLoginButton`
   (official widget) instead — login still works, just with Telegram's own button styling.

`NEXT_PUBLIC_TELEGRAM_BOT_ID` is added to `web.Dockerfile` (ARG/ENV) and the `web` build-args in
`.github/workflows/build.yml`, next to `NEXT_PUBLIC_TELEGRAM_BOT_USERNAME`.

## 7. i18n (`packages/i18n/locales/{ru,en,uz}/web.json`, `auth` namespace)

New keys: `modalTitle`, `providerTelegram`, `providerGoogle`, `providerSteam`, `providerEmail`,
`soon`, `agreePrefix`, `privacy`, `terms`, `back`. All three locales in the same PR.

## 8. Testing

`apps/web` has no unit suite. Verify: `tsc` (0), `eslint` (0 on new files), `prettier` clean,
and a manual run — open from header and `/login`; Email screen shows the form and
register/forgot links; Telegram popup fires (or the widget fallback renders); Google/Steam show
"скоро" and are inert; Esc / backdrop / × close; `/account` redirect to `/login` still opens the
modal. Smoke on ru/en/uz.

## 9. Documentation

- `apps/web/README.md` — note `NEXT_PUBLIC_TELEGRAM_BOT_ID`.
- No ADR required (UI change, no new dependency/pattern). The deferred Google/Steam OAuth work
  will get its own spec when built.

## 10. Definition of Done

- [ ] Login modal opens from header "Войти" and at `/login`; closes via Esc/backdrop/×.
- [ ] Telegram + Email work; Google + Steam render with "скоро" and are inert.
- [ ] Email screen reuses `AuthForm` (no duplicate Telegram button) with register/forgot links.
- [ ] `/account` auth-gate redirect to `/login` opens the modal; direct `/login` works.
- [ ] `NEXT_PUBLIC_TELEGRAM_BOT_ID` wired (Dockerfile + build.yml); widget fallback when unset.
- [ ] All three locales updated; `tsc`/`eslint`/`prettier` clean; manual run verified.
