# @yupay/miniapp — Telegram Mini App

Next.js 15. **Mobile-only** layout (max-width 480 px), CSR-heavy (no SEO indexing — never).

- `@telegram-apps/sdk-react` provides `<SDKProvider>`, `useBackButton`, `useMainButton`,
  `useHaptics`, etc.
- `initData` is sent to the API in the `Authorization: tma <raw>` header and validated
  server-side via HMAC. The client never trusts `initDataUnsafe` for authorisation.
- Theme params from Telegram are projected onto CSS custom properties (`--tg-*`) and
  consumed by Tailwind v4 via `@theme`.

```bash
make dev-miniapp
```
