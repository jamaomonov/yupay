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
