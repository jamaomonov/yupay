# 0072. Editorial blog bound to a catalogue brand

- **Status**: Accepted
- **Date**: 2026-09-12
- **Deciders**: owner, engineering
- **Tags**: backend | frontend | data | security

## Context and problem statement

The storefront already answers transactional queries (`/store/{brand}`) and
short how-tos. It does not own long-form informational URLs or brand
journalism (seasons, patches, live events). Those queries currently go to
competitors or the game's own site. We need a first-party editorial surface
that converts onto the money page without becoming a second catalogue or a
stored-XSS farm.

## Decision drivers

- Owner: every post has a primary brand; kinds are guide / news / update / event
- Same host (`/blog/{slug}`), not `blog.yupay.uz` — SEO and cookies stay one origin
- No ru→uz copy bleed (ADR-0006)
- HTML allowlist fail-closed; title field is the only H1
- Prices never persist in HTML; the buy card is a live catalogue read (M2)
- Mini App is out of v1 (not indexed)

## Considered options

1. **In-monolith `modules/blog`** — rows in Postgres, admin textarea (TipTap later), public GET
2. **WordPress / Ghost** — a second deploy and a second XSS surface
3. **Brandless industry blog** — no conversion card, no brand to rank for

## Decision outcome

**Chosen option:** Option 1. Content lives in this monolith. M1 ships schema,
sanitize, admin CRUD and public GET. M2 is the storefront. The admin editor
uses TipTap (`@tiptap/*` in `apps/admin`) so operators wrap a selection
instead of typing tags; cover and inline images use the existing R2
presign with `kind=blog_image` (png/jpeg/webp, same 5 MB cap as
`brand_hero`). FAQ editor UX remains later.

Publish stamps `published_at` once; archive keeps it. A brand may pin at most
two published posts. Event dates are a service rule, not a CHECK. Slug
changes after publish are refused by process (archive + new slug).

### Positive consequences

- One deploy, one locale rule, one media host (`r2_public_base_url`)
- Public GETs are cacheable and never return a draft
- Sanitize is I/O-free and ≥95% covered

### Negative consequences

- TipTap is an admin-only dependency; the public storefront still receives
  sanitized HTML, not editor JSON
- Scheduler for `scheduled` → `published` is deferred to M2

## Validation

- Integration tests: create → publish → public GET; 404 draft; 404 missing
  locale; slug 409; pin cap; archive keeps `published_at`
- Sanitize unit tests reject `h1`, `script`, off-host `img`, `javascript:` hrefs

## Alternatives considered (detail)

### Option 2 — WordPress / Ghost

A second origin and a CMS we do not operate. Rejected: threat model already
names stored XSS via catalogue markup; a second HTML store would duplicate
that fight.

### Option 3 — Brandless industry vertical

Owner declined: we do not have a generic industry to rank for, and the buy
card would have nothing to bind to.

## References

- Spec: `docs/superpowers/specs/2026-09-12-blog-design.md`
- Plan: `docs/superpowers/plans/2026-09-12-blog-m1.md`
- [ADR-0006](./0006-multilocale-strategy.md), [ADR-0018](./0018-r2-media-storage.md)
