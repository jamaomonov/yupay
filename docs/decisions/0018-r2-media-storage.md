# 0018. Media storage on Cloudflare R2 via presigned uploads

- **Status**: Accepted
- **Date**: 2026-05-25
- **Deciders**: @jamaomonov
- **Tags**: backend | infra | frontend

## Context and problem statement

The catalog stores image URLs as plain text columns: `brands.logo_url`,
`brands.hero_image_url`, `products.image_url`, `skus.image_url`. Today an
admin pastes any URL into a text input, so referenced images are scattered
across third-party hosts (random CDNs, free hosters, even direct paths to
producer-controlled domains). That's bad for three reasons:

- **Reliability** — third-party hosts disappear; broken thumbnails silently
  rot the catalog.
- **Performance** — images come from miscellaneous origins with no shared
  CDN/cache discipline; storefront paint suffers.
- **Cost / scale plan** — we already use Cloudflare R2 for `pg_dump`
  backups. Reusing it for media keeps the operational surface tiny and
  fits the single-VPS deployment goal.

We need a place to put admin-uploaded images and a write path that doesn't
require streaming files through the FastAPI process.

## Decision drivers

- Zero egress fees so storefront/miniapp can serve images straight from
  the storage host without budgeting for traffic.
- Keep the API process out of the upload data path — admins drag in 5 MB
  images, we don't want that traffic touching FastAPI's event loop.
- S3-compatible, so the same code path can later be pointed at MinIO
  (self-hosted) or any other S3-API store without a rewrite.
- Stay inside Cloudflare's free tier for the foreseeable future
  (≈10 GB storage, ≈2000 images).
- Single-PR scope: no schema migration, no backfill of existing
  third-party URLs.

## Considered options

1. **Cloudflare R2 + presigned PUT URLs** (chosen).
2. **MinIO self-hosted** inside the existing Docker Compose stack.
3. **AWS S3 (free tier)** or **Backblaze B2**.
4. **Stream the upload through FastAPI** to any of the above.

## Decision outcome

**Chosen option:** Cloudflare R2 with presigned PUT URLs, custom domain
`cdn.yupay.uz` for public reads.

### Positive consequences

- No egress fees → storefront serves the catalog at zero variable cost.
- Custom domain decouples the public URL from R2's internal hostname;
  swapping providers later is a one-line config change in
  `settings.r2_public_base_url`.
- FastAPI never sees image bytes. The presign endpoint is a local crypto
  operation; uploads bypass the API container entirely.
- We already maintain a Cloudflare account + R2 buckets (backups), so
  zero new vendors in the threat model / on-call surface.
- S3-compatible signature means any later move to MinIO is a config
  swap, not a code rewrite.

### Negative consequences

- One more set of credentials to keep in `sops`-encrypted env
  (`R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY`).
- Custom domain setup is a one-time manual step in the Cloudflare
  dashboard (Bucket → Settings → Connect Domain → `cdn.yupay.uz`), and it
  presupposes the zone is served by Cloudflare — which cost us a DNS
  migration off `ahost.uz`. Done 2026-07-20; see
  `docs/runbooks/media-cdn.md`. Until then the stack ran on the bucket's
  `pub-*.r2.dev` endpoint, whose rate limiting showed up as images that
  intermittently failed to load.
- Existing third-party URLs already in DB stay as-is. We do not
  backfill — see "Migration".

## Validation

- `make test-py` covers presign key derivation, MIME/size validation,
  and the rejection of unknown kinds.
- Smoke after deploy: admin uploads a logo via the new uploader, the
  cdn.yupay.uz URL renders in the storefront within one request.
- Cost dashboard in Cloudflare R2 stays in the free tier.

## Alternatives considered (detail)

### MinIO self-hosted

Pros: no new vendor, full control, zero per-month cost.
Cons: data path is `client → Caddy → MinIO container` — bandwidth
through Yandex Cloud is metered, the VPS becomes a hotspot, and there's
no global CDN. We'd reinvent half of R2's value.

### AWS S3 / Backblaze B2

Pros: mature.
Cons: egress fees (AWS) or daily download caps (B2) — the storefront
serves the same image hundreds of times per day; transfer charges or
throttling become a recurring concern. R2's zero-egress model wins on
the read pattern we actually have.

### Stream through FastAPI

Pros: full control over validation, virus scanning, etc.
Cons: blocks event-loop workers on big uploads, multiplies the bytes
on the wire (browser → API → R2 instead of browser → R2). With single-
VPS deployment this is the worst path.

## Migration

Existing `*_url` columns are left untouched. They remain `String(1024)`
and continue to accept arbitrary URLs (including legacy third-party
hosts). New admin uploads land in R2 and the column gets the
`https://cdn.yupay.uz/...` URL. A bulk migration of legacy URLs into R2
is deliberately out of scope; if/when it becomes useful it lands as a
separate one-off script + ADR.

## References

- Cloudflare R2 docs — Object Storage: <https://developers.cloudflare.com/r2/>
- ADR-0017 — Task-oriented admin refactor (the admin SPA is the upload UI).
- AGENTS.md §6 (no business logic in routers — `storage/routes.py`
  parses + dispatches to `service.presign_upload`).
