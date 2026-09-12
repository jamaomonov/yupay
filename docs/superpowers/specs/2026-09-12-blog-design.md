# Blog — Design

**Date:** 2026-09-12
**Status:** draft for implementation on `feat/blog`
**Shaped by:** owner conversation 2026-09-12. Decisions marked _(owner)_ came
from that thread; the rest is engineering that follows the repo contract
(`AGENTS.md`, ADR-0002 modular monolith, ADR-0006 locales, ADR-0018 media).

## 1. Context and goal

The storefront already has money pages (`/store/{brand}`), a thin programmatic
`/store/{brand}/how-to`, per-brand FAQs with `FAQPage` JSON-LD, a sitemap, and
`/llms.txt`. Those capture _transactional_ and _short how-to_ queries. They do
not capture:

- informational queries («как пополнить Mobile Legends в Узбекистане» as a
  long-form answer);
- **useful brand journalism** — a new season, a collab, what a patch changes
  for donators, a live event with a deadline.

The blog is both: a **source of information about the games we sell**, and a
path onto the brand page when the reader wants to top up. It is not a second
catalogue and not an auto-generated SKU farm.

## 2. Non-goals (v1)

- Mini App surface. Web is the SEO surface; the Mini App is not indexed
  (ADR-0006). A later card on History/Home can link out.
- Comments, likes, UGC. Abuse surface we already pay for on reviews.
- Named journalist accounts / TOTP. Author is the YuPay organisation.
- Auto-import of official patch notes. Thin duplicates lose to the game's own
  site and teach AI to ignore us.
- WordPress / Ghost / a second deploy. Content lives in this monolith.
- Unrestricted HTML in the database. The threat model already names stored XSS
  via catalogue-sourced markup; the blog is a larger body of the same risk.
- Steam-gifts style 4k-item crawl. One editorial URL per story.
- Self-serve merchant / partner bylines.

## 3. Naming and surfaces

| Thing                      | Name                                                               |
| -------------------------- | ------------------------------------------------------------------ |
| Domain module              | `modules/blog/`                                                    |
| Public storefront          | `apps/web` — `/{locale}/blog`, `/{locale}/blog/{slug}`             |
| Brand hub (optional index) | `/{locale}/blog?brand={slug}` — query, not a second URL tree in v1 |
| Admin SPA                  | `apps/admin/src/features/blog/`                                    |
| Public API                 | `/api/v1/blog/*` (anonymous, cacheable)                            |
| Admin API                  | `/api/v1/admin/blog/*`                                             |

Checked: no existing `/blog` route. `broadcasts` is Telegram-only and stays
that way — different allowlist, different audience.

## 4. How it sits next to what we already have

| Page                    | Job                                       | Blog must not replace               |
| ----------------------- | ----------------------------------------- | ----------------------------------- |
| `/store/{brand}`        | Buy. SKUs, checkout, reviews              | Prices, forms, player-check         |
| `/store/{brand}/how-to` | Short steps from catalogue `instructions` | Auto how-to; keep it                |
| Brand FAQ               | 4–8 short Qs, `FAQPage` on the money page | Long-form FAQ lives _in_ an article |
| `/blog/{slug}`          | Editorial: guide **or** news/update/event | Checkout itself                     |

Every post has **exactly one primary brand** (`primary_brand_id`, required)
_(owner)_. Optional extra brands (e.g. Steam + steam-gifts) are a join table.
A post with no brand is out of v1 — we do not have a generic «индустрия»
vertical to rank for, and the conversion card would have nothing to bind to.

`/store/{brand}` grows a «Новое по {brand}» block (M2): pinned + latest
published posts. The how-to page is unchanged.

## 5. Article kinds _(owner)_

| `kind`   | Reader intent                                  | Example                          |
| -------- | ---------------------------------------------- | -------------------------------- |
| `guide`  | how / where / how much                         | Как пополнить MLBB в Узбекистане |
| `news`   | what happened                                  | Новый сезон, коллаб              |
| `update` | what a patch changes (especially for donators) | Что изменится в пропуске         |
| `event`  | what is happening _now_                        | x2 UC до воскресенья             |

`event` carries `event_starts_at` / `event_ends_at` (UTC). While `now` is
inside the window the public index sorts the post above ordinary news and the
page shows a «сейчас» chip. After `event_ends_at` the post stays published
(history + SEO) with a «событие закончилось» chip — never 404.

## 6. Architecture

```
apps/admin  features/blog  ──admin JWT──▶  /api/v1/admin/blog/*
apps/web    app/[locale]/blog  ──anon GET──▶  /api/v1/blog/*
                         apps/api · modules/blog/
                         ├ api.py / routes.py / admin_routes.py
                         ├ service.py
                         ├ sanitize.py     (HTML allowlist, CDN-only <img>)
                         ├ models.py
                         └ schemas.py
              catalog (brand slug, live Offer for the buy card)
              storage (presign kind=blog_image)
```

- Fulfilment, payments, wallet: **untouched**.
- `catalog` is read through `catalog.api` (or the existing storefront
  `getBrandDetail` on the web). `blog` does not join SKU prices in SQL.
- The buy card on an article is a **live** brand/product fetch, not a price
  snapshotted into the HTML. Stale numbers in prose are a content rule, not a
  schema field.
- ISR / Data Cache: public GETs tagged `blog`; admin publish calls
  `revalidateTag` is not available from FastAPI — web keeps `revalidate = 300`
  like brand pages (ADR-0060) and the sitemap `revalidate = 3600`. `updated_at`
  is the sitemap `lastmod` (the catalogue still lacks one; do not repeat that).

## 7. Data model

### 7.1 `blog_posts`

| Column                              | Notes                                                                                     |
| ----------------------------------- | ----------------------------------------------------------------------------------------- |
| `id`                                | UUID string, `yupay.core.ids`                                                             |
| `kind`                              | `guide` \| `news` \| `update` \| `event` + CHECK                                          |
| `status`                            | `draft` \| `scheduled` \| `published` \| `archived` + CHECK                               |
| `primary_brand_id`                  | FK `brands.id` ON DELETE RESTRICT (do not cascade-wipe journalism)                        |
| `show_buy_card`                     | bool, default true                                                                        |
| `pin_on_brand`                      | bool, default false. Service cap: **at most 2** published pins per brand                  |
| `cover_image_url`                   | nullable text, must be our CDN when set                                                   |
| `event_starts_at` / `event_ends_at` | timestamptz, nullable; required together when `kind=event` (service, not a brittle CHECK) |
| `published_at`                      | set on first transition to `published`; left in place on archive                          |
| `scheduled_for`                     | timestamptz, used when `status=scheduled` (M2 scheduler; column exists in M1)             |
| `created_at` / `updated_at`         | timestamptz                                                                               |

Indexes: `(status, published_at DESC)` for the public feed;
`(primary_brand_id, status, published_at DESC)` for the brand block;
partial `(primary_brand_id) WHERE pin_on_brand AND status = 'published'`.

### 7.2 `blog_post_translations`

One row per locale that has copy. **No cross-locale fallback** (same rule as
brand highlights: a missing `uz` row is omitted from `uz`, not filled with
`ru`).

| Column                          | Notes                                                                                                              |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `post_id` + `locale`            | PK, locale in `ru` \| `en` \| `uz`                                                                                 |
| `slug`                          | kebab `[a-z0-9-]{3,96}`, **UNIQUE(locale, slug)** — ru `/blog/kak-popolnit-mlbb`, en `/en/blog/how-to-top-up-mlbb` |
| `title`                         | the page H1. Not repeated as an `<h1>` in the body                                                                 |
| `excerpt`                       | ≤ 280 chars, used as meta description fallback and card blurb                                                      |
| `body_html`                     | sanitized HTML (see §8)                                                                                            |
| `seo_title` / `seo_description` | optional overrides                                                                                                 |

A post may be `published` with only `ru` filled — `en`/`uz` 404 until those
rows exist. Chrome (nav, chips, empty states) still ships all three locales
in the same PR, per ADR-0006.

### 7.3 `blog_post_brands`

Extra related brands. Unique `(post_id, brand_id)`. Primary is **not**
duplicated here.

### 7.4 `blog_post_faqs`

Optional Q/A pairs used both on the page and as `FAQPage` JSON-LD (must match
visible text — GEO rule). `(post_id, locale, sort_order)`, question + answer
plain text (no HTML).

## 8. Body format and the admin editor

**Source of truth in v1 is sanitized HTML**, not a second TipTap JSON column.
The admin editor (M3: TipTap) serialises to HTML; the API runs `sanitize`
before persist. A later JSON column is a migration, not a v1 requirement.

### 8.1 Allowlist

Tags: `p`, `h2`, `h3`, `ul`, `ol`, `li`, `a`, `img`, `blockquote`, `strong`,
`em`, `code`, `pre`, `table`, `thead`, `tbody`, `tr`, `th`, `td`, `hr`, `br`.

- **No `h1`.** The title field is the only H1 (one per URL).
- **No `script`, `style`, `iframe`, `object`, `svg`, event handlers.**
- `a[href]`: `http` / `https` / relative `/…` only. `rel=noopener` on
  external. Internal storefront links stay relative so locale prefixing works.
- `img[src, alt]`: `src` must be our public media host (`cdn.yupay.uz` /
  settings). `alt` required, ≤ 200 chars. SVG refused (ADR-0018 / storage
  already refuses SVG for logos — same stored-XSS reason).
- Table tags (`table`, `thead`, `tbody`, `tr`, `th`, `td`) persist with
  no attributes. TipTap always writes `style` / `colspan` / `colgroup`;
  `sanitize` strips those and drops `colgroup`/`col` before the rest of
  the allowlist runs. Attributes on every other tag still reject.

M1 admin can ship a `<textarea>` plus a sanitized preview. M3 replaces it
with TipTap (toolbar: H2/H3, lists, link, image upload, table, quote) and
optional «карточка бренда» / «FAQ» inserts that are _not_ raw HTML — they
are flags/rows (`show_buy_card`, `blog_post_faqs`).

### 8.2 Images

New `storage` `MediaKind`: `blog_image` (png/jpeg/webp only, same budget as
`brand_hero`). Presign from admin; persist the public URL on the post or
inline `<img>`.

## 9. Public contract

Anonymous, rate-limited like other public GETs. No Idempotency-Key (reads).

| Endpoint                         | Notes                                                                                                                              |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `GET /blog`                      | `locale`, optional `brand` (slug), `kind`, `cursor`. Published + locale row only. Events in-window first, then `published_at` desc |
| `GET /blog/{slug}`               | locale from `Accept-Language` / `?locale=` like catalogue. 404 if unpublished or locale missing                                    |
| `GET /blog/by-brand/{brandSlug}` | latest N + pins, for the brand page block                                                                                          |
| `POST /blog/{slug}/view`         | anonymous unique view; sets `yp_blog_reader`; Idempotency-Key                                                                      |
| `POST /blog/{slug}/like`         | anonymous like; same cookie; Idempotency-Key                                                                                       |
| `DELETE /blog/{slug}/like`       | unlike; no-op if never liked                                                                                                       |

List items carry: slug, kind, title, excerpt, cover, published*at, updated_at,
primary brand `{slug, name}`, `event*\*`, `pin_on_brand`, `like_count`,
`view_count`. Detail adds `body_html`, faqs, related brand slugs,
`show_buy_card`. **Never** a draft. Views/likes are cookie-hashed, not IP
(ADR-0073).

## 10. Admin contract

Admin JWT + existing role gate (same as catalogue FAQs). Mutations take
`Idempotency-Key`.

- `GET/POST /admin/blog/posts`
- `GET/PATCH /admin/blog/posts/{id}` (translations upserted in the same PATCH
  as an array — one write, like brand translations)
- `POST /admin/blog/posts/{id}/publish` \| `archive` \| `schedule`
- Soft archive, no hard delete in v1 (URLs may be indexed).

## 11. Storefront (M2) — branding

This is `apps/web`, not a new app. Tokens and type are already in
`apps/web/src/app/globals.css`:

- Surfaces: `--bg` / `--card` / `--card-2`, radius `--radius-xl` (cards),
  `--radius-2xl` (hero).
- Type: **Unbounded** display (H1, section titles), **Inter** body, **JetBrains
  Mono** eyebrows / dates.
- Accent: electric lime `--primary` on chips (kind, «сейчас»), links hover,
  focus ring. Body links in articles: lime underline, not a second blue.
- Layout: `max-w-[1200px]` chrome like the header; **article measure
  `max-w-[720px]`** for body text. Cover 16:9 in a `rounded-2xl` card.
- Header grows a «Блог» nav link (ru/en/uz) next to «Магазин».
- Buy card: reuse storefront card language (cover, name, «от {price}», lime
  CTA to `/store/{slug}`) — do not invent a second product tile.

No light theme on web (the storefront is dark-only). Do not copy the merchant
cabinet's light-theme requirement here.

## 12. SEO and AI answers

- Unique H1 = `title`. Meta from `seo_*` or `excerpt`.
- `alternates` / `hreflang` / `x-default` via existing `alternates(locale, path)`
  — only for locales that _have_ a translation row.
- JSON-LD (escaped with `serializeJsonLd`):
  - `guide` → `Article` + optional `HowTo` if the body has a numbered list we
    can split (same idea as `/how-to`);
  - `news` / `update` / `event` → `NewsArticle`;
  - always `BreadcrumbList`;
  - `FAQPage` iff `blog_post_faqs` is non-empty and matches visible FAQ;
  - `about` = the brand (name + URL). Live `Offer` stays on the buy card /
    brand page, not frozen into the article.
- First visible paragraph of a `guide` should be a 40–60 word standalone
  answer (content rule, not a schema field).
- Sitemap: each published translation as its own URL; `lastmod = updated_at`
  truncated to the day (same honesty rule as today's sitemap).
- `/llms.txt`: add a «Гайды и новости» section — latest ~20 published `ru`
  titles with URLs. Do not dump bodies.
- Visible «обновлено {date}» on the article.
- Copy rules (same discipline as the merchant landing): no invented delivery
  ETAs; no hardcoded prices in prose (the live card is the number).

## 13. i18n chrome

New `packages/i18n` namespace `web.blog` (and `admin.blog`). All three
locales in the same PR as the first UI that uses a key.

## 14. Observability

No new money path. Bounded Prometheus labels if we add a counter:
`blog_posts_published_total{kind}` is enough. Do not label by slug.

## 15. Rollout

| Phase  | Delivers                                                                    |
| ------ | --------------------------------------------------------------------------- |
| **M1** | Module + migration; sanitize; admin CRUD (textarea); public GET; tests; ADR |
| **M2** | Web index + article; header link; brand block; sitemap; `llms.txt`; JSON-LD |
| **M3** | TipTap editor; `blog_image` uploads; FAQ editor; event/pin/schedule UX      |

M1 is sellable to an admin who pastes HTML. M2 is what Google and readers
see. M3 is what makes weekly news viable for a human operator.

## 16. Resolved-question log

| Question          | Decision                                                              |
| ----------------- | --------------------------------------------------------------------- |
| Domain            | Same host, `/blog`, not `blog.yupay.uz` _(owner / SEO)_               |
| Linked to brands  | Required primary brand _(owner)_                                      |
| Kinds             | guide, news, update, event _(owner)_                                  |
| Editor            | Allowlisted HTML; TipTap in M3, not raw tags _(engineering)_          |
| H1                | Title field only _(SEO)_                                              |
| Locales           | Per-translation slugs; no ru→uz bleed _(ADR-0006 + catalogue lesson)_ |
| Mini App          | Out of v1                                                             |
| Prices in HTML    | Forbidden; live buy card                                              |
| Official scrapers | Out of v1                                                             |
