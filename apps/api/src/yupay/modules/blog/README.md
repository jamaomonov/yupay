# blog

Editorial posts bound to a catalogue brand: guides, news, updates and
time-bounded events. The storefront (M2) renders them for SEO and as a
path onto `/store/{brand}`; this module owns the rows and the HTML
allowlist.

**Spec:** `docs/superpowers/specs/2026-09-12-blog-design.md`

## Rules

- Every post has exactly one `primary_brand_id`. Extra brands are a join
  table; the primary is not duplicated there.
- Copy is per-locale (`blog_post_translations`). No ru→uz fallback.
- `body_html` is persisted only after `sanitize`. No `<h1>`
  in the body — the title field is the page H1. The admin editor is TipTap
  and emits only the allowlist; cover and inline images upload as
  `kind=blog_image` to R2.
- `status=published` is what the public GET serves. Archive keeps
  `published_at` so an indexed URL can explain why it vanished later;
  v1 does not hard-delete.
- At most two published `pin_on_brand` posts per primary brand (service).
- Prices never live in HTML. The buy card (M2) reads the live catalogue.

## Tables

- `blog_posts` — kind, status, primary brand, pin, event window, cover.
- `blog_post_translations` — slug unique per locale, title, excerpt, body.
- `blog_post_brands` — extra related brands.
- `blog_post_faqs` — Q/A that must match visible FAQ (GEO / `FAQPage`).

## Public surface (`api.py`)

Re-exports models plus `router` (`/blog`) and `admin_router` (`/admin/blog`).
Public GETs are anonymous and cacheable. Admin mutations require
`Idempotency-Key` (≥16 chars) and the `admin` role.

## How to publish without breaking SEO

- Do not change a published slug. Archive the old post and create a new
  slug if the URL must move.
- Publish only when every shipped locale has a non-empty sanitized body.
  A missing locale 404s; it does not fall back to `ru`.
- At most two published pins per primary brand.
