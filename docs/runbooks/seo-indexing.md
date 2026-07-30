# Runbook — SEO indexing & IndexNow

> How the storefront is discovered by search engines, and what to do when pages
> aren't indexed or the favicon isn't showing.

## What's automated

- **Sitemap** (`apps/web/src/app/sitemap.ts`) → `https://yupay.uz/sitemap.xml`: all
  public paths × 3 locales with hreflang alternates, `priority`,
  `changeFrequency`, and **`lastModified`** (the build/deploy time — the one
  sitemap hint Google actually uses; no per-page content timestamp is exposed to
  the storefront, so a redeploy is treated as "content may have changed").
- **robots.txt** (`apps/web/src/app/robots.ts`) allows all except `/api`, `/admin`
  and points at the sitemap.
- Every indexable page ships `robots: index,follow`, a self-canonical, hreflang,
  and og tags. Favicon: `/favicon.ico` (48×48 + 32×32) + `/icon.svg` (512²).

## IndexNow (Bing / Yandex — NOT Google)

Google does not support IndexNow; this speeds recrawl on **Bing and Yandex**.

- Ownership key file: `apps/web/public/<key>.txt` (served at
  `https://yupay.uz/<key>.txt`, body = the key). Current key committed there.
- Ping after a deploy that changed content:
  ```bash
  make indexnow          # submits every sitemap URL
  # or a subset:
  INDEXNOW_URLS="https://yupay.uz/store/pubg-mobile" node scripts/indexnow.mjs
  ```
  The script verifies the key file is live first (so it must run **after** the
  web deploy), then POSTs the URL list to `api.indexnow.org`.
- To rotate the key: generate a new one (`openssl rand -hex 16`), rename the
  `public/*.txt` file to `<newkey>.txt` with that content, update
  `scripts/indexnow.mjs`'s default `KEY`, deploy, then `make indexnow`.

## When pages aren't (fully) indexed on Google

Google indexes new/low-authority domains **slowly and selectively** — partial
indexing over days/weeks is normal, not a bug. The GSC banner "Данные
обрабатываются, повторите через день" is reporting lag (1–3 days), not an error.

Diagnose + push, in order:

1. **GSC → Indexing → Pages**: read the _status_ of un-indexed URLs.
   - _Discovered – currently not indexed_ → crawl budget / low authority.
   - _Crawled – currently not indexed_ → Google judged it not worth indexing yet
     (thin/duplicate/low trust) → deeper content + internal links + time.
   - _Duplicate / alternate canonical_ → a canonical problem (canonicals here are
     clean self-referencing, so this shouldn't appear).
2. **URL Inspection → Request indexing** for the home first (the favicon depends
   on the home being indexed), then `/store` and top brand pages.
3. **Authority**: external links (Telegram channel/bio, socials, directories) are
   the biggest lever for a young domain.
4. Confirm `https://yupay.uz` shows **"URL is on Google"** in URL Inspection.

## When the favicon doesn't show in Google

Nothing to fix if the checks above pass (they do: valid 48×48 `.ico` + SVG,
reachable, declared on the home page, home indexable). Google only renders the
favicon after it **recrawls and processes the home page**, which typically takes
**2–6 weeks** after the home page is indexed — a few days is too early. It
appears primarily on mobile SERPs. If it's still missing weeks after the home
page is confirmed indexed, re-check the `<link rel="icon">` on the home page and
that `/favicon.ico` returns 200 (not behind auth/redirect).
