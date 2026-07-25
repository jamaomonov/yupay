# Home promo cards (miniapp)

Replace the Home hero carousel and Popular strip with a two-card promo row.

## Goal

Surface CS2 skin market and Steam top-up as primary entry points on the miniapp Home, matching the provided layout (title + subtitle top-left, 3D art bottom-right) while using YuPay theme tokens.

## Scope

- Remove `HeroCarousel` and `PromoStrip` from `Home.tsx`.
- Add `HomePromoCards`: two equal cards in a 2-column grid.
- Links: skins → `/cs2-market`, Steam → `/topup/steam`.
- Assets: `sellskins.webp`, `steam2.png` under `apps/miniapp/src/assets/home/`.
- i18n keys in `ru` / `en` / `uz` for titles and subtitles.
- Delete unused `HeroCarousel` (and its `src/assets/hero/*`) if nothing else imports them.
- Drop unused keys `home.popular`, `home.badge.*` if no longer referenced; leave `hero.*` only if still used elsewhere.

## Non-goals

- Backend / catalog changes.
- Changing page title `home.title`.
- Building real skin-sell checkout (card only deep-links to market UI).

## Visual

- Card: `bg-surface-1`, `border-border`, `rounded-2xl`.
- Title: white semibold; subtitle: `text-body-muted`.
- Illustration: absolute bottom-right, `object-contain`, no flat purple gradients from the mock.
- `whileTap` scale like other Home cards.
