# 0080. Reseller site for non-technical resellers

- **Status**: Accepted
- **Date**: 2026-09-17
- **Deciders**: owner, Claude
- **Tags**: frontend | seo | product

## Context and problem statement

`reseller.yupay.uz` (app `apps/merchant`) had one audience in mind — a
developer integrating `/merchant/v1` — and it showed everywhere: the manual
order path in the cabinet surfaced `sku_id`, «ID для API», raw backend
statuses and an id of the shape `manual-<uuid>`, on a screen a Telegram-channel
admin has to use with a subscriber waiting in their DMs. Two audience reviews
done in parallel (`docs/superpowers/specs/2026-09-17-reseller-audience-review.md`,
the cabinet-and-copy read, and `docs/superpowers/specs/2026-09-17-reseller-seo-design.md`,
the SEO/AEO read) converged on the same finding from two directions: the
**larger** audience is not the developer. It is the Telegram-channel reseller
who fulfils orders by hand — 10-60 orders/day off a phone, no developer on
staff, choosing a supplier on price, trust and "what happens if I mistype the
player id", never on API shape. That audience was not written for anywhere on
the site, and the site could not have reached them if it had been: no
`sitemap.xml`, no `robots.txt`, no JSON-LD, a single `generateMetadata` for
the entire domain, no canonical/hreflang — while the cabinet, which earns
nothing from being indexed, was open to it. Two competitors that matter here —
g-engine (also our own Steam-gifts supplier) and NovaGifts — position
squarely for "shops and bots reselling top-ups"; neither shows up for the
queries that should be ours. Those queries are actually held by content
sites, FazerCards and FoxReload, on the strength of articles, guides and a
glossary, not a landing page. The ru/uz queries were open ground we were not
even contesting.

## Decision drivers

- One entity, **YuPay**, not two products under one confusing word — the site
  must not read as a second «партнёры» program (partners.yupay.uz already
  owns that word).
- Both audiences belong on one page: splitting authority across two domains
  or two products costs more than one page serving two intents costs.
- Answer-engine readiness, not only classic SEO: indexability first
  (sitemap/robots/JSON-LD/canonical), then direct-answer paragraphs a crawler
  or an assistant can lift whole, literal-question headings matching how the
  audience actually asks ("где брать товар оптом", not "wholesale API"),
  structured data (`FAQPage`/`BreadcrumbList`/`TechArticle`), and AI crawlers
  explicitly welcomed rather than blocked.
- The owner's copy rules, which override both source specs: no deposit/top-up
  mention anywhere in marketing copy, no discounts/percentages/prices (so no
  `/prices` page and no price examples), the offer's draft banner untouched,
  no invented requisites, copy «без воды», and the header badge stays
  `reseller`.

## Considered options

1. **One landing, admin-first with developers below the fold, plus
   server-rendered intent pages (`/telegram`, `/api`, `/faq`).** [Chosen]
2. **Two sites or two subdomains, one per audience.** Rejected: it splits
   backlink and topical authority the SEO design doc is trying to consolidate,
   doubles the maintenance surface (two sitemaps, two robots files, two
   copies of every legal/ownership fact), and reopens the「two products, one
   word」confusion the drivers above rule out.
3. **Keep the developer-only positioning of today and fix nothing about
   audience.** Rejected: the business review measured this directly —
   `POST /merchant/v1/validate/player` had near-zero traffic, and the
   developer-shaped cabinet converts the numerically larger audience at
   roughly zero. Leaving it as is optimizes for the audience that was
   already finding the site.

## Decision outcome

**Chosen option:** Option 1. What shipped, across Tasks 1-4 (+1b, 2b) of
`docs/superpowers/plans/2026-09-17-reseller-audience-seo.md`:

- **Cabinet de-jargon.** The manual-order path (catalog tile, order box,
  orders list, order detail, the account strip) speaks product names, not
  `sku_id`/raw statuses/`manual-<uuid>`; product names are resolved through
  the cabinet BFF rather than invented client-side.
- **A rewritten landing**, admin-first, developers below the fold, built from
  `merchant.json` strings in all three locales, «без воды» per the owner.
- **Three server-rendered intent pages** — `/telegram`, `/api`, `/faq` —
  each answering one literal question the audience actually asks, with
  `FAQPage`/`BreadcrumbList`/`TechArticle` JSON-LD.
- **A SEO layer ported from the storefront**: `lib/seo.ts`, a `robots.txt`
  route naming the AI crawlers and a Content-Signal header, `sitemap.ts` with
  hreflang, per-page `generateMetadata`, `llms.txt`. The cabinet itself is
  left `noindex` rather than removed from the sitemap by omission.
- **One footer link and one `llms.txt` section on the storefront**
  (`apps/web`) pointing at the program.
- **The owner's rulings, applied throughout**: no deposit/top-up mention in
  marketing copy anywhere; no discounts, percentages, or prices, and
  therefore no `/prices` page; the offer page and its «Черновик» banner
  untouched; no invented company requisites or manager names; the header
  badge stays `reseller`; the affiliate program is named by its real name
  (partners.yupay.uz) only in `faq.q11`/`a11` and in `llms.txt` — everywhere
  else the vocabulary is «Оптом» / «для перепродажи», never «партнёры».

**Deliberately not built**, each for a stated reason rather than an oversight:

- `/prices` and any price examples — owner ruling; no percentages or figures
  in marketing copy at all.
- `/how-to-earn` — same ruling; a page about earning without a number on it
  answers nothing.
- `/catalog/[brand]` public catalog pages — the long-tail SEO play the design
  doc flags as high-value, deferred to a follow-up once the base layer is
  measured.
- The storefront-style blog series for the reseller audience — deferred; the
  base indexability work (sitemap/robots/JSON-LD) has to land and be measured
  before content investment is justified.
- Markdown views + IndexNow for the reseller site — the storefront already
  carries this pattern (ADR-0072); porting it to `apps/merchant` is a
  follow-up, not part of this pass.
- An MCP server for the reseller program — out of scope; assistants are
  served today through `llms.txt` and the Markdown/JSON-LD surface the
  storefront already proved out.
- The in-cabinet player-ID check — P1 in the business review
  (`docs/superpowers/specs/2026-09-17-reseller-audience-review.md` §4.3): the
  machine-API logic (`modules/merchants/validate.py`,
  `POST /merchant/v1/validate/player`) already exists, the cabinet BFF proxy
  route does not. Left for a follow-up task.
- The deposit top-up flow — out of scope by owner rule (no top-up mention in
  marketing, and the flow itself was never in this plan's scope).

### Positive consequences

- The larger audience — Telegram-channel resellers fulfilling by hand — now
  has copy and pages written for how they actually search and think, instead
  of inheriting developer-shaped pages by default.
- The site is indexable for the first time: sitemap, robots (AI crawlers
  welcomed), JSON-LD, per-page metadata, hreflang. It can now compete for the
  ru/uz queries FazerCards and FoxReload currently hold uncontested.
- A monthly measurement panel (12 prompts across five assistant engines, a
  Loki query for crawler traffic, and a webmaster-panel checklist) is now
  part of the runbook, so the effect of this work is checkable rather than
  assumed — see `docs/runbooks/merchant-b2b.md` § SEO/AEO: что смотреть.

### Negative consequences

- `FAQPage` JSON-LD now sits on four pages (`/`, `/telegram`, `/api`,
  `/faq`); Google has historically honoured at most one `FAQPage` result per
  domain, so three of the four markups may render no rich result even though
  all four are valid.
- The cabinet is crawlable-but-`noindex`, not access-gated — a change of
  intent, not of exposure; nothing there stops a crawler from fetching a page
  it is merely asked not to index.
- `/docs/*` page titles are now unique (previously a single domain-wide
  title covered them), which is a metadata-only change but touches every
  page under that path.
- The offer page's «Черновик» banner remains the blocker the business review
  flagged: it is untouched by this ADR's scope, on the owner's own ruling,
  and it is still the thing standing between this work and paid traffic.
- Cloudflare's «Block AI Scrapers and Crawlers» toggle must be confirmed
  **off** for `reseller.yupay.uz` before rollout, or the `robots.txt` welcome
  this ADR ships is overridden at the edge; that check is the owner's, not
  automatable from this repo.

## Validation

- The 12-prompt monthly panel and the Loki AI-crawler query in
  `docs/runbooks/merchant-b2b.md` § SEO/AEO: что смотреть, first run **before**
  the pages are announced so there is a baseline to compare against.
- Success bands (from the design doc, carried into the runbook): 4 weeks —
  indexed in Google and Bing, 60+ pages in coverage, `GPTBot` visible in logs;
  8 weeks — non-zero impressions for the «оптом» query cluster, ≥2/12 prompts
  name YuPay in at least one engine; 16 weeks — ≥5/12 prompts, including the
  Uzbekistan-niche control prompt, plus organic-sourced registrations.

## Alternatives considered (detail)

### Option 2 — two sites/domains

Splits whatever backlink and topical authority either audience's traffic
would build, since Bing/Yandex/Google and the assistants that crawl them all
credit one host at a time. It also duplicates every fact that must stay
consistent between the two (legal entity, offer terms, support contact),
doubling the chance the two drift and a prospect reads two different
answers to the same question depending on which door they walked through.

### Option 3 — developer-only positioning, unchanged

The business review's own traffic read (near-zero calls to
`validate/player`) is the evidence against this: the audience currently
served is not the audience placing 10-60 hand-fulfilled orders a day. Leaving
the site as-is does not fail loudly — it fails by simply never converting the
larger group, which is why it took an audience review rather than an
incident to surface.

## References

- `docs/superpowers/specs/2026-09-17-reseller-audience-review.md` — the
  cabinet-and-copy business review (jargon inventory, P1/P2 backlog).
- `docs/superpowers/specs/2026-09-17-reseller-seo-design.md` — the SEO/AEO
  design (competitor read, measurement panel, page-by-page checklist).
- `docs/superpowers/plans/2026-09-17-reseller-audience-seo.md` — the
  implementation plan; where its strings differ from either spec, the plan
  wins.
- [ADR-0068](./0068-merchant-b2b-foundation.md) — the merchant B2B
  foundation this site sits on top of.
- [ADR-0069](./0069-merchant-machine-api.md) — the machine API `/telegram`
  and `/api` describe.
- [ADR-0070](./0070-merchant-webhooks.md) — the outgoing webhooks referenced
  from the developer-facing pages.
- [ADR-0076](./0076-merchant-cabinet.md) — the cabinet as its own origin,
  which this ADR leaves crawlable-but-`noindex`.
- [ADR-0072](./0072-editorial-blog.md) — the storefront's `llms.txt` /
  Markdown-view pattern this ADR ports the SEO layer from and defers porting
  Markdown/IndexNow from.
