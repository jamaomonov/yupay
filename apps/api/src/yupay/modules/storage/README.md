# `storage` module

Public surface: [`storage.api`](api.py).

## Responsibility

Issue short-lived presigned PUT URLs so the admin SPA can upload images
(and, for broadcasts, one video/GIF/document) directly to a Cloudflare
R2 bucket. Returns the public URL the admin should persist into the
relevant DB column (`brands.logo_url`, `brands.hero_image_url`,
`products.image_url`, `skus.image_url`, a blog cover / inline `<img>`,
the broadcast's media column, or one entry of a product form field's
`help_images` list — see "Media kinds" below).

This module **does not** stream bytes — uploads bypass FastAPI entirely.
See [ADR-0018](../../../../../../docs/decisions/0018-r2-media-storage.md).

## Layout

| File         | Role                                                                                    |
| ------------ | --------------------------------------------------------------------------------------- |
| `client.py`  | Lazy, cached boto3 S3 client pointed at R2 (sigv4 + path-style).                        |
| `service.py` | Key derivation (`<kind>/<yyyy>/<mm>/<ulid>.<ext>`), MIME/size validation, presign call. |
| `schemas.py` | Pydantic request/response shapes for the admin endpoint.                                |
| `routes.py`  | `POST /api/v1/admin/media/presign-upload` (admin-only).                                 |
| `api.py`     | Public surface — what other modules / `api/v1/__init__.py` are allowed to import.       |

## Config

Reads from :class:`yupay.core.config.Settings`:

- `R2_ACCOUNT_ID` — Cloudflare account ID (for the R2 endpoint host).
- `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` — bucket-scoped R2 token.
- `R2_BUCKET_MEDIA` — bucket name (default `yupay-media`).
- `R2_PUBLIC_BASE_URL` — public read prefix (default `https://cdn.yupay.uz`).
- `R2_PRESIGN_TTL_SECONDS` — how long the PUT URL stays valid (default 300).
- `MEDIA_MAX_UPLOAD_BYTES` — per-upload size cap for image kinds (default 5 MiB).
- `MEDIA_ALLOWED_MIME` — global MIME superset (default
  png/jpeg/webp/svg+xml/gif/mp4/pdf). This is **not** the whole story —
  see "Media kinds" below for what each `kind` actually accepts.
- `BROADCAST_MEDIA_MAX_UPLOAD_BYTES` — per-upload size cap for
  `kind="broadcast_media"` (default 20 MiB).

## Media kinds

`presign_upload` validates `content_type` against a **per-kind**
allowlist (`_KIND_ALLOWED_MIME` in `service.py`), not the global
`MEDIA_ALLOWED_MIME` list — the global list only controls which MIME
types have a known file extension. This is deliberate: `MEDIA_ALLOWED_MIME`
had to grow to cover broadcast attachments, but image kinds must not
silently start accepting a video just because the global list did.

| `kind`                                                                                     | Allowed Content-Types                                         | Size cap                                   |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------- | ------------------------------------------ |
| `brand_logo`, `brand_hero`, `product_image`, `sku_image`, `blog_image`, `field_help_image` | `image/png`, `image/jpeg`, `image/webp` (no SVG)              | 5 MB (`MEDIA_MAX_UPLOAD_BYTES`)            |
| `broadcast_media`                                                                          | those three, plus `image/gif`, `video/mp4`, `application/pdf` | 20 MB (`BROADCAST_MEDIA_MAX_UPLOAD_BYTES`) |

`field_help_image` is what a product form field's `help_images` (see
`yupay.modules.catalog.schemas.FormField`/`HelpImage`) uploads through —
one screenshot in a «Где найти?» walkthrough, landing under its own
`field_help_image/<yyyy>/<mm>/<ulid>.<ext>` prefix rather than mixing with
brand logos and blog covers. `catalog.schemas.HelpImage` validates the
stored URL against `is_own_media_url` (below) before accepting it, and
caps the list at 6 images per field — both enforced server-side, in the
Pydantic model, not just at upload time.

`is_own_media_url(url)` (`storage.service`, re-exported from
`storage.api`) is the single predicate for "this URL points at our own R2
media bucket" — it compares `url`'s scheme + host against
`r2_public_base_url` and requires the path to sit under that prefix.
Every caller that must refuse a URL pointing at a third-party host reuses
this instead of re-deriving the prefix; `catalog.schemas.HelpImage` is the
first such caller.

## Upload workflow

```
SPA               API                              R2
 │   POST /admin/media/presign-upload              │
 │ ──────────────────────────────▶                 │
 │   { upload_url, public_url, key, expires_in }   │
 │ ◀──────────────────────────────                 │
 │                                                 │
 │   PUT upload_url  Content-Type: image/png       │
 │ ──────────────────────────────────────────────▶ │
 │   200 OK                                        │
 │ ◀──────────────────────────────────────────────│
 │                                                 │
 │   PATCH /admin/brands/{id}   { logo_url: public_url }
 │ ──────────────────────────────▶                 │
```

## Why no migration job?

Existing third-party URLs in the catalog remain valid. New uploads land
in R2; old ones keep working. If a bulk migration becomes desirable it
ships as a separate one-off script + ADR addendum.
