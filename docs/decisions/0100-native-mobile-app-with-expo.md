# 0100. A native mobile app built with Expo inside the monorepo

- **Status**: Accepted
- **Date**: 2026-10-18
- **Deciders**: @jamaomonov
- **Tags**: frontend | infra | payments

## Context and problem statement

YuPay sells through the web storefront (`apps/web`) and the Telegram Mini App
(`apps/miniapp`). Customers who do not live in Telegram reach us only through a browser tab,
and a browser cannot send a push when an order lands. A competitor selling the same goods to
the same audience (topit.store) has been in both the App Store and Google Play since
mid-2024, paying through local acquirers rather than the stores' billing. The owner wants
YuPay in both stores.

Two constraints shape the choice. Apple rejects an app that is a thin wrapper around a
website (App Review Guideline 4.2), so the app must be native screens, not a web view. And
the stores' rules on digital goods (Apple 3.1.1, Google Play Payments) say in-app sales of
digital content go through their billing; the competitor shows the rule is enforced
loosely for third-party game top-ups paid on an acquirer's page, but it is a standing risk,
sharpest for gift cards, which Apple names explicitly.

## Decision drivers

- Reuse what already exists: the generated API client, the three locale catalogues, the zod
  schemas and the TypeScript team skills.
- One build pipeline for iOS and Android, from a Mac without Xcode on day one.
- A breaking API change must fail at build time in the app, not in a customer's hands.
- Native enough to clear Guideline 4.2.

## Considered options

1. **Expo (React Native) in the monorepo** as `apps/mobile`.
2. **Expo in a separate repository** consuming a published API client.
3. **Flutter.**
4. **Capacitor wrapping the web storefront.**

## Decision outcome

**Chosen option:** 1, because it is the only option that reuses `@yupay/api-client`,
`@yupay/i18n` and `@yupay/utils` as source and keeps the app in the same type check as the
API it calls.

Shape:

- **Stack.** Expo SDK 58, expo-router (file-based navigation), TanStack Query and Zustand
  as in web, react-hook-form + zod for forms, expo-secure-store for the refresh token,
  expo-notifications for push. Styling is React Native `StyleSheet` over one token module
  (`src/theme`) that mirrors the web palette (`apps/web/src/app/globals.css`) and adds a
  light theme; `packages/ui` is DOM-only and is not reused.
- **Builds.** EAS Build and EAS Submit (Expo's cloud) produce and upload store binaries; no
  store build runs in GitHub Actions. CI runs lint, typecheck and unit tests for
  `apps/mobile` only when it or a shared package changes.
- **Over-the-air updates.** EAS Update ships JS-only fixes between store releases; anything
  that changes what the app does goes through review.
- **Payments.** The app creates the order and the payment intent through the same API as
  the web storefront and opens the acquirer's page in the system in-app browser
  (`expo-web-browser`). The return URL stays on the storefront origin
  (`https://yupay.uz/checkout/return`, which `_safe_return_url` already accepts); when the
  browser closes the app polls the order. No acquirer, no webhook and no payment route
  changes for the first version.
- **Sign-in.** Google and Steam open in the in-app browser. iOS additionally offers Sign in
  with Apple, which Guideline 4.8 requires once a third-party login is present — a backend
  addition, not in the first version's scope.
- **First version scope.** Catalogue, brand page with the player check, checkout, orders,
  profile, push on delivery. CS2 skins, the wallet top-up, P2P and gift cards stay out:
  skins need the trade-link flow, and gift cards carry the clearest store-billing risk.
- **Identifiers.** App name «YuPay», iOS bundle id and Android package `uz.yupay.app`, URL
  scheme `yupay`.

### Positive consequences

- No second copy of the catalogue, pricing or order types: the app breaks on the same
  `make gen-api` that changes them.
- Both stores from one codebase; the owner can try every build on a phone through Expo Go
  before a store build exists.

### Negative consequences

- Screens are written a third time (web, mini app, app); only tokens and logic are shared.
- The store-billing rule is a standing risk: a review can ask for in-app purchase or remove
  the app. Gift cards are kept out of the iOS build until the app has a review history.
- A third push channel (APNs/FCM) and a device-token table are new backend surface.
- pnpm's isolated `node_modules` and Metro need explicit configuration; a Metro upgrade can
  break module resolution in a way web never sees.

## Validation

- Both store reviews pass with the first version's scope.
- A test order paid through Click in the app reaches `delivered` and the push arrives.
- A field renamed in the API fails `pnpm --filter @yupay/mobile typecheck`.

## Alternatives considered (detail)

### Option 2 — separate repository

Isolates CI minutes, but the API client would have to be published and versioned, and a
contract change would surface only when someone bumps it. Path filters give the same CI
isolation inside the monorepo.

### Option 3 — Flutter

Mature and fast, but Dart shares nothing with the existing code: the API client, locales and
validation would be rewritten and kept in sync by hand.

### Option 4 — Capacitor around the storefront

Cheapest to build and the likeliest to be rejected under Guideline 4.2; the storefront is
also server-rendered Next.js, which Capacitor cannot bundle as static files.

## References

- [ADR-0016](./0016-miniapp-vite-stack.md) — the mini app's own stack, the other
  non-web surface.
- Apple App Review Guidelines 3.1.1, 4.2, 4.8; Google Play Payments policy.
- Mockup agreed with the owner 2026-10-18 (light and dark themes).
