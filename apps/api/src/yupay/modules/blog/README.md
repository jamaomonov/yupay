# blog

Editorial posts bound to a catalogue brand: guides, news, updates and
time-bounded events. The storefront (M2) renders them for SEO and as a
path onto `/store/{brand}`; this module owns the rows and the HTML
allowlist. Storefront `/blog` and `/blog/{slug}` also content-negotiate
`Accept: text/markdown` (same rewrite as home and `/store`).

**Spec:** `docs/superpowers/specs/2026-09-12-blog-design.md`

## Rules

- Every post a reader can reach has exactly one `primary_brand_id`. Extra
  brands are a join table; the primary is not duplicated there. A **draft**
  may have none — that is how an imported article arrives, before anyone has
  decided what it sells — and `CHECK (primary_brand_id IS NOT NULL OR status
= 'draft')` is what keeps the public queries honest: all of them inner-join
  `brands` through that column and all of them filter to `published`.
  `publish_post` and `schedule_post` refuse without a brand.
- Copy is per-locale (`blog_post_translations`). No ru→uz fallback.
- `body_html` is persisted only after `sanitize`. No `<h1>`
  in the body — the title field is the page H1. The admin editor is TipTap
  and emits only the allowlist; cover and inline images upload as
  `kind=blog_image` to R2. Table tags are rewritten to drop TipTap's
  `style` / `colspan` / `colgroup` so a round-trip save does not 422.
- `status=published` is what the public GET serves. Archive keeps
  `published_at` so an indexed URL can explain why it vanished later;
  v1 does not hard-delete.
- At most two published `pin_on_brand` posts per primary brand (service).
- Prices never live in HTML. The storefront buy card reads the live catalogue.

## Tables

- `blog_posts` — kind, status, primary brand, pin, event window, cover,
  denormalized `like_count` / `view_count`.
- `blog_post_likes` / `blog_post_views` — unique `(post_id, reader_hash)`
  from the `yp_blog_reader` cookie (ADR-0073). Not IP.
- `blog_post_translations` — slug unique per locale, title, excerpt, body.
- `blog_post_brands` — extra related brands.
- `blog_indexnow_pings` — outbox for Bing/Yandex IndexNow on publish/archive
  (ADR-0074). The worker POSTs only in prod; a miss does not unpublish.
- `blog_imported_posts` — one row per upstream article (ADR-0077): what we
  pulled, what we wrote, and when. Two hashes — the source fields we consume
  and everything we stored — so a re-sync can tell "unchanged upstream" from
  "edited here" and never overwrite the second.
- `blog_post_faqs` — Q/A that must match visible FAQ (GEO / `FAQPage`).
  The admin form edits them per locale on the same page as the body.
  A PATCH replaces FAQ and translation rows after a flush so unique
  `(locale, sort_order)` / `(locale, slug)` do not 409 on a no-op save.

## Imported copy (Bunzy)

`bunzy_client.py` reads their feed, `markdown_html.py` maps GFM onto the
allowlist, `bunzy_import.py` writes the draft, and
`apps/scheduler/.../jobs/bunzy_import.py` runs it hourly. Nothing there
publishes and nothing there overwrites an edit — see ADR-0077 for the full
mapping table and `docs/runbooks/blog-bunzy-import.md` for operating it.

Two things to know before touching that path:

- `markdown_html` rewrites the **token stream**, not the finished HTML. A new
  construct is handled by retagging or dropping its token, never by a regex
  over the output.
- `sanitize_body` still runs over the result, and a test asserts it accepts
  that output **unchanged**. The converter is the mapping, not the guard.

## Public surface (`api.py`)

Re-exports models plus `router` (`/blog`) and `admin_router` (`/admin/blog`).
Public GETs are anonymous and cacheable. Guest `POST /blog/{slug}/view`
and `POST`/`DELETE /blog/{slug}/like` take `Idempotency-Key` (≥16).
Admin mutations require the key and the `admin` role.

## How to publish without breaking SEO

- Publish and archive enqueue IndexNow for every translation URL plus the
  locale `/blog` index. Google ignores IndexNow; Yandex/Bing do not.
- Do not change a published slug. Archive the old post and create a new
  slug if the URL must move.
- Publish only when every shipped locale has a non-empty sanitized body.
  A missing locale 404s; it does not fall back to `ru`.
- At most two published pins per primary brand.
