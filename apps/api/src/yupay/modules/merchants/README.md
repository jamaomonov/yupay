# `merchants`

B2B reseller accounts: a merchant, its cabinet operator(s), and the API keys
its server uses against `/merchant/v1`. This is the schema module that every
other part of the merchant B2B feature (the machine API, the cabinet BFF, the
deposit ledger, admin) builds on.

**Spec:** `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`

## Terminology note

Acquirers call **us** the merchant (Click/Payme `merchant_id` credentials);
in this module the merchant is the reseller.

## Tables

- `merchants` — the reseller account: `title`, `status` (`active`/`frozen`),
  and a dormant `markup_adjustment_pp` reserved for a future per-merchant
  pricing override (spec §8.3).
- `merchant_users` — cabinet operators. One user per merchant in v1; the FK
  already permits more.
- `merchant_api_keys` — machine credentials for `/merchant/v1`: a public
  `key_id` (`ypm_`-prefixed) and the secret held **encrypted at rest**
  (`secret_enc` / `secret_nonce`, migration 0070 — see "Storage" below), with
  an optional IP allowlist, a `last_used_at` stamp and a `revoked_at`
  tombstone. See "Machine-API authentication" below.

## Deposit ledger

The merchant's prepaid balance is a **ledger balance**, never a column.
`merchant_deposit` is a debit-normal account kind (like `user_wallet`),
owned by `owner_type="merchant", owner_id=<merchant_id>, currency="USD"`
— USD-only in v1 (spec §7). Every movement posts through
`wallet.service.post`, so idempotency-by-key and all-or-nothing legs are
inherited from the ledger, not rebuilt here.

The posting table is authoritative — M2 must not re-derive directions:

| Event                       | Legs                                             |
| --------------------------- | ------------------------------------------------ |
| Support credits top-up (M1) | `D merchant_deposit / C house_payments_received` |
| (M2) order charge           | `C merchant_deposit / D house_payments_received` |
| (M2) refund on failure      | `D merchant_deposit / C house_payments_received` |

Only the first row is implemented in M1: `service.credit_deposit` posts it
with `kind="merchant_deposit_credit"` and the caller's idempotency key, so a
replay returns the original transaction. `service.deposit_balance` reads the
balance (`Decimal("0")` when no account exists yet — the read creates
nothing). Freezing a merchant (`service.set_status`) blocks orders (M2),
never money in: support can always credit a frozen merchant.

## Pricing

The wholesale price formula — the **one home**, per
`docs/superpowers/plans/2026-09-06-merchant-b2b-m1.md` Task 5 — lives in
`pricing.py` and nowhere else:

```
price = ceil_to_cent(
    effective_cost(sku) * (1 + (sku.b2b_markup_pct + (merchant.markup_adjustment_pp ?? 0)) / 100)
)
```

Four pure functions, all `Decimal`, no DB access:

- `effective_cost(sku) -> Decimal | None` reads `sku.cost_usdt`. `None`
  means the SKU is **not sellable B2B** — excluded from the merchant
  catalog, orders for it rejected. It never falls back to `price_usd` or
  any other retail figure (spec §8.2).
- `merchant_markup_pct(sku, merchant)` adds the dormant per-merchant
  `markup_adjustment_pp` (spec §8.3, `None` for every merchant in v1) to
  the SKU's uniform `b2b_markup_pct`.
- `merchant_price(cost, markup_pct)` rounds up to the cent
  (`ROUND_CEILING`) — rounding down would erase margin on cheap SKUs
  invisibly, a cent at a time.
- `violates_margin_floor(cost, price, floor_pct)` is the only global
  pricing control (spec §8.3): it catches a fat-fingered per-SKU markup
  (including one that goes negative — Task 4 deliberately added no DB
  `CHECK` on `b2b_markup_pct`) and cost spikes a stale markup no longer
  covers. Callers read `settings.merchant_margin_floor_pct` (default `2`)
  and pass it in; the pure functions never read settings themselves.

**Nothing else in the codebase may reimplement this formula.** The one
sanctioned exception is the admin SPA's client-side price _preview_ next to
the markup field (Task 8, labelled «предварительно») — display-only, never
authoritative; the server always recomputes and is the source of truth for
what a merchant is actually charged.

Import these from `api`, not from `pricing` directly — the same rule as
every other symbol in this module.

## Admin surface

Everything support needs to run a pilot merchant by hand (Task 6), all
admin-gated (`require_admin`), business logic imported through the `api`
facade only. Two routers in `admin_routes.py` (mounted by `api/v1` directly
from that file — the facade never exports a router, or it would close a
cycle back through the route stack, same rule as `affiliate.routes`):

- `POST`/`GET /admin/merchants` — create a reseller; list every merchant
  with its USD deposit balance joined in **one grouped query**
  (`admin.list_merchants_with_balances`, the batch variant of
  `deposit_balance` — no per-merchant balance read).
- `POST /admin/merchants/{id}/freeze|unfreeze` — persists `status` only in
  M1; ordering is what M2 will block.
- `POST /admin/merchants/{id}/deposit-credits` — posts via
  `service.credit_deposit`. **Requires** `Idempotency-Key`; the ledger key
  is namespaced `merchant-credit:{merchant_id}:{client_key}` so one
  client's key can never replay another merchant's transaction. The ledger
  replays by key **without comparing parameters**, so the response's
  `amount` is the transaction's actual (original) amount — a mismatched
  replay is visible to the admin UI, and `balance` rides along. See
  `docs/architecture/sequence-diagrams/merchant-deposit-credit.mmd`.
- `GET /admin/merchants/{id}/transactions` — the merchant's deposit ledger,
  newest first (`admin.list_deposit_transactions`, one grouped query). Each
  row carries the **signed** deposit delta (positive = balance up; M2 order
  charges will surface as negative rows unchanged), the credit's `note`, and
  the `admin:<id>` actor. Read-only; a typo'd merchant id is a 404, never a
  plausible-looking `[]`.
- `PATCH /admin/catalog/skus/{id}/b2b` (`markup_pct?`, `visible_b2b?`),
  `POST /admin/catalog/b2b/bulk-markup` (`brand_slug | category`,
  `markup_pct` — one UPDATE, returns the affected count) and
  `PATCH /admin/catalog/brands/{id}/b2b` (`visible_b2b`) — the catalog B2B
  knobs. No pricing math in routes; the markup is stored verbatim and the
  order-time margin floor is the guard (spec §8.3).

- `POST /admin/merchants/{id}/api-keys` — mint a machine credential
  (`label?`, `ip_allowlist?`). **The secret is in this response and nowhere
  else, ever.** `GET .../api-keys` lists every key ever issued, newest
  first, revoked ones included, and its response model has no `secret`
  field at all. `DELETE .../api-keys/{key_id}` revokes: it sets
  `revoked_at`, is naturally idempotent (a second call returns the FIRST
  timestamp rather than moving it), and matches on `(merchant_id, key_id)`
  so one merchant's id in the path can never revoke another's credential.

The non-ledger writes accept an optional `Idempotency-Key` and replay
through the generic `(scope, key)` store (`core.idempotency`), like the
other admin write endpoints. Each scope is **per resource** —
`merchants.sku_b2b:{sku_id}`, `merchants.brand_b2b:{brand_id}`,
`merchants.bulk_markup:{target}`, `merchants.set_status.{to}:{merchant_id}`,
`merchants.api_key_create:{merchant_id}`,
`merchants.api_key_revoke:{merchant_id}:{key_id}` — because an admin client
that mints one key per session and reuses it across two SKUs would
otherwise get the first SKU's response replayed for the second, and the
second SKU would silently never be patched.

Key creation is the one endpoint where the replay snapshot is deliberately
**not** the response: the stored body carries `secret: null`, so a retry
returns the original `key_id` with no secret. `idempotent_responses` has no
reaper, and a usable credential sitting there in the clear forever is worse
than telling an operator whose first response was lost to revoke the key and
issue another.

The admin SPA screens for this surface live in
`apps/admin/src/features/merchants/` (`/merchants` list + create,
`/merchants/:id` freeze / deposit credit / ledger). The deposit-credit form
is the UI half of the replay-visibility mechanism above: it compares the
response's `amount` with what the operator typed and warns loudly on a
mismatch, mints one idempotency key per logical credit attempt (stable
across retries), and blocks double-submit while a credit is in flight.

The catalog B2B knobs (Task 8) live on the catalog edit screens instead —
`apps/admin/src/features/catalog/b2b.ts` plus a `SkuB2bCard` /
`BrandB2bCard` on the SKU and brand editors: the `visible_b2b` switches,
the per-SKU markup with the sanctioned «предварительно» price preview
(see "Pricing" above — `previewB2bPrice` mirrors `pricing.merchant_price`
in BigInt math and names this module as the authority), and the bulk
"наценка всем SKU бренда" action, confirm-gated because it rewrites the
whole brand's markups, reporting `affected` from the response. The read
side those controls render from is `AdminBrandOut.visible_b2b` /
`AdminSkuOut.{visible_b2b,b2b_markup_pct}` in the catalog module's admin
list DTOs — admin-only, never on the public catalog DTOs.

## Machine-API authentication (`/merchant/v1`)

**This section is the contract.** Third parties implement against the text
below without reading our source, so it must stay complete and it must not
change without a new API version — `/merchant/v1` is consumed by code nobody
but its owner can redeploy.

> **Status:** the authentication layer is live; the endpoints it guards land
> with the rest of M2. The examples below use `GET /merchant/v1/me`, the first
> of them, and are forward-looking until it ships. The scheme itself is final.

Base URL: **`https://api.yupay.uz`**. All requests are HTTPS. All strings are
UTF-8. Every `\n` below is a single LF byte (`0x0A`) — never CRLF.

### Credentials

Support issues a key from the admin surface and hands over two values:

| Value    | Example                                     | Notes                                              |
| -------- | ------------------------------------------- | -------------------------------------------------- |
| `key_id` | `ypm_9j2v…` (36 chars)                      | Public. Sent on every request.                     |
| `secret` | `ypms_Rk8…` (48 chars, 256 bits of entropy) | **Shown once.** Store it; we cannot show it again. |

Several keys can be live at the same time, which is what makes rotation
zero-downtime: issue the new one, deploy it, then revoke the old one.

We hold the secret **encrypted at rest** (XSalsa20-Poly1305 under an
application key that is not in the database), which is what lets us verify
your signature without keeping key material in the clear. Honest boundary: a
stolen database dump on its own yields nothing usable; an attacker holding
both the dump and the application key is another matter, and the controls that
bound that are revocation and the per-key IP allowlist.

### The signature

Three headers on every request:

```
X-Merchant-Key:       <key_id>
X-Merchant-Timestamp: <unix seconds, digits only>
X-Merchant-Signature: <lowercase hex HMAC-SHA256>
```

The signature is `HMAC_SHA256(secret, canonical)` — the secret's UTF-8 bytes
are the key, with **no derivation step** — where the canonical string is five
fields joined by LF:

```
canonical = timestamp + "\n" + METHOD + "\n" + raw_path + "\n" + raw_query + "\n" + sha256_hex(body)
```

| Field              | What exactly                                                                                                                                                    |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `timestamp`        | The **same characters** you put in the header. Do not re-format it.                                                                                             |
| `METHOD`           | Upper-case: `GET`, `POST`.                                                                                                                                      |
| `raw_path`         | The path **exactly as it appears on the request line**, percent-encoded, no scheme, no host, no query: `/merchant/v1/orders/my%2Forder`.                        |
| `raw_query`        | The query string **as sent**, without the leading `?`. Empty string when there is no query — the field is still there, so the string still has four separators. |
| `sha256_hex(body)` | Lowercase hex SHA-256 of the raw request body. A GET signs `sha256("")` = `e3b0c442…b855`, not an empty field.                                                  |

Three consequences worth stating outright:

- **Sign the bytes you send.** Re-serialising your JSON between signing and
  sending changes the signature. Sign the exact byte string, then send it.
- **Do not decode the path or the query before signing.** They are signed in
  their encoded form, which is what removes every ambiguity about how a
  character in your own `merchant_order_id` should be spelled.
- **The query string is covered.** `?limit=10` and `?limit=100000` are
  different requests and need different signatures.

### Worked example

`GET /merchant/v1/me` at `1757000000`, no query, no body:

```
canonical = "1757000000\nGET\n/merchant/v1/me\n\ne3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

Python:

```python
import hashlib, hmac, time, httpx

KEY_ID = "ypm_…"
SECRET = "ypms_…"
BASE = "https://api.yupay.uz"


def call(method: str, path: str, query: str = "", body: bytes = b"") -> httpx.Response:
    ts = str(int(time.time()))
    canonical = "\n".join(
        (ts, method.upper(), path, query, hashlib.sha256(body).hexdigest())
    ).encode()
    signature = hmac.new(SECRET.encode(), canonical, hashlib.sha256).hexdigest()
    url = f"{BASE}{path}?{query}" if query else f"{BASE}{path}"
    return httpx.request(
        method,
        url,
        content=body,
        headers={
            "X-Merchant-Key": KEY_ID,
            "X-Merchant-Timestamp": ts,
            "X-Merchant-Signature": signature,
            "Content-Type": "application/json",
        },
    )
```

Node 18+ (no dependencies):

```js
import crypto from "node:crypto";

const KEY_ID = "ypm_…";
const SECRET = "ypms_…";
const BASE = "https://api.yupay.uz";

export async function call(method, path, query = "", body = "") {
  const bodyBytes = Buffer.from(body, "utf8");
  const ts = Math.floor(Date.now() / 1000).toString();
  const bodyHash = crypto.createHash("sha256").update(bodyBytes).digest("hex");
  const canonical = [ts, method.toUpperCase(), path, query, bodyHash].join("\n");
  const signature = crypto
    .createHmac("sha256", SECRET) // the secret itself is the key — no pre-hashing
    .update(canonical, "utf8")
    .digest("hex");

  const url = query ? `${BASE}${path}?${query}` : `${BASE}${path}`;
  return fetch(url, {
    method,
    body: bodyBytes.length ? bodyBytes : undefined,
    headers: {
      "X-Merchant-Key": KEY_ID,
      "X-Merchant-Timestamp": ts,
      "X-Merchant-Signature": signature,
      "Content-Type": "application/json",
    },
  });
}
```

### Rules the server applies, in order

The whole path is drawn in
`docs/architecture/sequence-diagrams/merchant-api-auth.mmd`.

| Failure                                                      | Status | `code`                |
| ------------------------------------------------------------ | ------ | --------------------- |
| Too many requests (per IP, or per key once authenticated)    | 429    | —                     |
| A credential header missing                                  | 401    | `missing_credentials` |
| Timestamp not digits-only, or more than **±300 s** from ours | 401    | `stale_timestamp`     |
| Unknown `key_id`, revoked key, or wrong signature            | 401    | `invalid_credentials` |
| This exact signature was already used                        | 401    | `signature_replayed`  |
| Merchant frozen                                              | 403    | `merchant_frozen`     |
| Caller's address not in the key's IP allowlist               | 403    | `ip_not_allowed`      |

The three credential failures return **one identical body** on purpose: the
payload does not reveal whether a `key_id` exists, and the HMAC is computed
either way so the crypto cost does not either.

### Replay: the ±300 s window and single-use signatures

Reject-outside-±300 s bounds how long a captured request stays interesting.
Inside that window, **each signature may be used exactly once** — the second
request carrying the same signature gets `signature_replayed`.

Two practical rules follow:

- **Re-sign every retry.** A client that retries a timed-out request must
  compute a fresh signature (a fresh timestamp is usually enough). Re-sending
  the identical headers will fail.
- **Do not send byte-identical requests more than once per second.** The
  timestamp has one-second resolution, so two otherwise-identical requests in
  the same second produce the same signature and the second is rejected. Poll
  no faster than once a second, or vary something (a `cursor`, a filter).

When order creation ships it will additionally be idempotent on
`merchant_order_id` (spec §9.3), so a re-signed retry of a create returns the
existing order rather than placing a second one. Until then, the ±300 s window
and the single-use signature are the whole of the replay story.

### Errors

RFC 7807 `application/problem+json`. `type` is the stable identifier; `code`
is a short discriminator on the auth and business failures. A sample body:

```json
{
  "type": "https://app.yupay.uz/errors/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "invalid merchant credentials",
  "code": "invalid_credentials"
}
```

The complete set of `type` URIs this API can return:

| `type`                                             | Status | When                                             |
| -------------------------------------------------- | ------ | ------------------------------------------------ |
| `https://app.yupay.uz/errors/unauthorized`         | 401    | Any authentication failure                       |
| `https://app.yupay.uz/errors/forbidden`            | 403    | Frozen merchant, IP not allowed                  |
| `https://app.yupay.uz/errors/not-found`            | 404    | No such order / SKU / resource                   |
| `https://app.yupay.uz/errors/validation`           | 422    | Request body or parameters rejected              |
| `https://app.yupay.uz/errors/conflict`             | 409    | Same `merchant_order_id`, different body         |
| `https://app.yupay.uz/errors/rate-limited`         | 429    | Either rate-limit axis                           |
| `https://app.yupay.uz/errors/upstream-unavailable` | 502    | A supplier we depend on could not be reached     |
| `https://app.yupay.uz/errors/internal`             | 500    | Our bug. Retry with a fresh signature; report it |

The `type` host is an identifier namespace, not a URL to fetch.

### Rate limits

Two independent counters, both fixed 60-second windows:

| Axis                  | Limit          | Applies to                           |
| --------------------- | -------------- | ------------------------------------ |
| Per source IP address | **600 / 60 s** | Every request, before authentication |
| Per `key_id`          | **600 / 60 s** | Requests whose signature verified    |

Both return `429` with a `Retry-After` header in seconds; wait that long
rather than retrying immediately. The per-key counter is charged only after a
signature verifies, so someone who observes your `key_id` in a header cannot
spend your budget. Each live key has its own counter, so a rotation window
briefly has two.

### IP allowlist

A key with an allowlist only authenticates from those addresses; entries are
single addresses (`198.51.100.7`) or CIDR blocks (`203.0.113.0/24`), IPv4 or
IPv6, and host bits inside a block are ignored when matching. No allowlist
means no filter. Set one from the cabinet or ask support.

## Implementation map

| Concern                                                    | Where                                                         |
| ---------------------------------------------------------- | ------------------------------------------------------------- |
| Wire format: key/secret minting, canonical string, digests | `signing.py` — the one home; nothing else may re-derive these |
| Secret encryption at rest                                  | `core/crypto.py` (purpose `yupay:merchants:apikey:v1`)        |
| Credential lifecycle (create / list / revoke)              | `service.py`, via the `api` facade                            |
| Request verification + the FastAPI dependency              | `auth.py`                                                     |
| Admin HTTP surface                                         | `admin_routes.py`                                             |

`auth.merchant_auth` is the dependency every `/merchant/v1` endpoint sits
behind. **Import it from `merchants.auth` directly, never from
`merchants.api`**: it takes its session from `api.v1.deps.db_session` so the
endpoint behind it shares one transaction, which means the facade cannot
re-export it without closing an import cycle back through the v1 route stack —
the same rule the routers in `admin_routes` follow. It supports **byte-body
endpoints only**: it reads `await request.body()`, and an endpoint declaring
`Form(...)`/`UploadFile` would send FastAPI down the `request.form()` branch,
consuming the stream without populating the cache the dependency relies on.

### Storage

The secret is encrypted, not hashed, and the reason is structural: an HMAC
cannot be verified without the key material, so a one-way digest either
forbids HMAC or forces the digest itself to be the signing key — which is
storing key material in the clear under a reassuring name. `core/crypto.py`
gives each purpose an HKDF-derived key from the one `INVENTORY_ENC_KEY` input,
so merchant secrets and voucher codes never share a key. The same protection
`inventory_codes` has had all along, applied to the instrument that is worth
more.

### Rate limiting internals

Two axes, one counter implementation (`auth.ip_guard.hit_counter`):

- **per IP** — `guard_ip(request, bucket="merchant-api")`, ceiling
  `auth_ip_guard_bucket_max["merchant-api"]`. No `subject` is passed:
  `guard_ip`'s subject axis is capped by the single global
  `auth_ip_guard_subject_max` (10), which would throttle every merchant to ten
  requests a minute.
- **per key** — `settings.merchant_api_key_rate_max`, charged after the
  signature verifies.

Brute force is not the threat model — the secret is 256 bits and compared with
`compare_digest` — throughput is, which is what both numbers are sized for.

### Inherited assumption: the caller's address

The allowlist is enforced against `core.client_ip`, which takes the first
`X-Forwarded-For` entry with **no trusted-proxy check**; its safety rests
entirely on the shared edge overwriting that header rather than appending to
it. That assumption previously only decided which rate-limit counter got
charged. Hardening `client_ip` itself is filed for M3 (it is repo-wide), and
the mitigating fact is that the allowlist is **defence-in-depth on top of the
HMAC**, never the primary control: an attacker who can spoof the header still
has no secret.

## Status

Schema (M1 Task 1), the deposit service (M1 Task 3), wholesale pricing
(M1 Task 5), the admin endpoints (M1 Task 6), the admin SPA screens
(M1 Tasks 7–8), and API-key issuance plus the signed-request dependency
(M2 Task 2, wire format and storage revised after review) are in place. The
machine API's own endpoints and the cabinet BFF land in the rest of M2+.
