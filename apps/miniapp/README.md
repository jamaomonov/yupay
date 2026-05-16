# `@yupay/miniapp`

Telegram Mini App for YuPay. Vite + React 19 + wouter, see [ADR-0016](../../docs/decisions/0016-miniapp-vite-stack.md).

## Run

```bash
pnpm --filter @yupay/miniapp dev          # http://localhost:5173 standalone
docker compose up -d miniapp              # http://localhost:3001 via container nginx
```

Build is a static Vite output served by nginx. No SSR, no runtime — see ADR-0016.

## Layout

```
src/
  main.tsx            Vite entry
  App.tsx             wouter routes + providers
  index.css           Tailwind v4 + design tokens (Deep Space / Electric Lime)
  pages/              Home, TopUp, History, Settings, not-found
  components/
    layout/           Shell, Header, BottomNav
    ui/               shadcn-style primitives (only the 14 we use)
  hooks/              use-mobile, use-toast
  lib/
    constants.ts      mock catalog (GAMES, HISTORY, ...) — replaced when API lands
    utils.ts          cn() helper
  assets/             brand logos / hero backgrounds
```

## API wiring

Currently mock-only. Real API integration arrives in a follow-up — replaces
`lib/constants.ts` reads with TanStack Query calls to `/api/v1/catalog/*` and
hooks Telegram auth via `Authorization: tma <initData>`.
