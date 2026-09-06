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
  `key_id` (`ypm_`-prefixed) and a SHA-256 `secret_hash`, with an optional
  IP allowlist, a `last_used_at` stamp and a `revoked_at` tombstone. See
  "Machine-API authentication" below.

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
change without a new API version — `/merchant/v1` is consumed by code
nobody but its owner can redeploy.

### Credentials

Support issues a key from the admin surface and hands over two values:

| Value    | Example                                     | Notes                                |
| -------- | ------------------------------------------- | ------------------------------------ |
| `key_id` | `ypm_9j2v…` (36 chars)                      | Public. Sent on every request.       |
| `secret` | `ypms_Rk8…` (48 chars, 256 bits of entropy) | **Shown once.** Store it; we cannot. |

Several keys can be live at the same time, which is what makes rotation
zero-downtime: issue the new one, deploy it, then revoke the old one.

### The signing key

We store only the SHA-256 of the secret, and that digest is also what both
sides key the HMAC with. So the first thing an integration does is derive
it, once, at startup:

```
signing_key = lowercase_hex(SHA256(secret))     # 64 characters
```

```python
signing_key = hashlib.sha256(secret.encode()).hexdigest()
```

```js
const signingKey = crypto.createHash("sha256").update(secret).digest("hex");
```

An HMAC cannot be verified without the key material, so the digest we store
_is_ the key — be clear about what that buys and what it does not. It does
**not** make a database dump harmless: whoever holds `secret_hash` can sign
requests. It does mean the secret string you pasted into your own config is
not recoverable from our database. The controls that matter against a dump
are revocation and the per-key IP allowlist. `signing.py`'s module docstring
carries the full reasoning and the alternative that was rejected.

### The signature

Every request carries three headers:

```
X-Merchant-Key:       <key_id>
X-Merchant-Timestamp: <unix seconds>
X-Merchant-Signature: hex(HMAC_SHA256(signing_key, canonical))
```

where the canonical string is exactly four fields joined by `\n`:

```
canonical = f"{timestamp}\n{method}\n{path}\n{body}"
```

- `timestamp` — the **same characters** you put in the header. Do not
  re-format it.
- `method` — upper-case (`GET`, `POST`).
- `path` — the URL path only, **no query string**, no scheme, no host:
  `/merchant/v1/orders`. Percent-decoded (sign `/merchant/v1/orders/my
order`, not `…/my%20order`), which is why identifiers you put in a path
  should stay URL-safe.
- `body` — the raw request body **byte for byte**, appended after the final
  `\n`. Sign the bytes you actually send: re-serialising the JSON on either
  side changes the signature. A GET has an empty body and contributes
  nothing after that newline.

The header value is lowercase hex; we accept surrounding whitespace and
upper-case hex too. Query parameters are **not** covered by the signature —
never put anything security-relevant in a query string (§9.2 of the spec
forbids identifiers in URLs anyway, because the edge access log records
query strings verbatim).

Worked example, `GET /merchant/v1/me` at `1757000000` with no body:

```
canonical = b"1757000000\nGET\n/merchant/v1/me\n"
```

```python
import hashlib, hmac, time, httpx

signing_key = hashlib.sha256(secret.encode()).hexdigest()

def call(method: str, path: str, body: bytes = b"") -> httpx.Response:
    ts = str(int(time.time()))
    canonical = f"{ts}\n{method}\n{path}\n".encode() + body
    signature = hmac.new(signing_key.encode(), canonical, hashlib.sha256).hexdigest()
    return httpx.request(
        method,
        "https://api.yupay.uz" + path,
        content=body,
        headers={
            "X-Merchant-Key": key_id,
            "X-Merchant-Timestamp": ts,
            "X-Merchant-Signature": signature,
            "Content-Type": "application/json",
        },
    )
```

### Rules the server applies, in order

The whole path is drawn in
`docs/architecture/sequence-diagrams/merchant-api-auth.mmd`.

| Failure                                                     | Status | `code`                |
| ----------------------------------------------------------- | ------ | --------------------- |
| Too many requests (per IP, or per key once authenticated)   | 429    | —                     |
| A credential header missing                                 | 401    | `missing_credentials` |
| Timestamp not an integer, or more than **±300 s** from ours | 401    | `stale_timestamp`     |
| Unknown `key_id`, revoked key, or wrong signature           | 401    | `invalid_credentials` |
| Merchant frozen                                             | 403    | `merchant_frozen`     |
| Caller's address not in the key's IP allowlist              | 403    | `ip_not_allowed`      |

Errors are RFC 7807 `application/problem+json`; `type` is the stable URI and
`code` the short discriminator to switch on. The three credential failures
return **one identical body** on purpose, and take the same work to produce
(the server signs against a dummy key rather than returning early), so
neither the payload nor the response time reveals whether a `key_id` exists.

The ±300 s window is the replay defence: a captured request cannot be
replayed after five minutes. Inside the window, order creation is idempotent
on `merchant_order_id` (spec §9.3), which is what makes a replay harmless
rather than merely unlikely.

**Clock skew is the most common integration bug** — hence its own error
code. Sync the calling server's clock (NTP) before debugging anything else.

### IP allowlist

A key with `ip_allowlist` set only authenticates from those addresses;
entries are single addresses (`198.51.100.7`) or CIDR blocks
(`203.0.113.0/24`), IPv4 or IPv6, and host bits in a block are ignored when
matching. A NULL (or empty) allowlist means no filter. The address compared
is the one `core.client_ip` resolves — the real client behind the edge
proxy, not the proxy.

### `last_used_at`

Stamped on every authenticated request, best effort: it never fails a
request, and it is throttled to at most one write a minute per key (every
request UPDATEing one row would serialise a merchant's own traffic on that
row's lock). Treat it as "this key was in use around then", not as a request
log.

## Implementation map

| Concern                                                    | Where                                                         |
| ---------------------------------------------------------- | ------------------------------------------------------------- |
| Wire format: key/secret minting, canonical string, digests | `signing.py` — the one home; nothing else may re-derive these |
| Credential lifecycle (create / list / revoke)              | `service.py`, via the `api` facade                            |
| Request verification + the FastAPI dependency              | `auth.py`                                                     |
| Admin HTTP surface                                         | `admin_routes.py`                                             |

`auth.merchant_auth` is the dependency every `/merchant/v1` endpoint sits
behind. **Import it from `merchants.auth` directly, never from
`merchants.api`**: it takes its session from `api.v1.deps.db_session` so the
endpoint behind it shares one transaction, which means the facade cannot
re-export it without closing an import cycle back through the v1 route
stack — the same rule the routers in `admin_routes` follow.

### Rate limiting

Two axes, one counter implementation (`auth.ip_guard.hit_counter`):

- **per IP** — `guard_ip(request, bucket="merchant-api")`, ceiling
  `auth_ip_guard_bucket_max["merchant-api"]` (600 per 60 s). No `subject` is
  passed: `guard_ip`'s subject axis is capped by the single global
  `auth_ip_guard_subject_max` (10), which would throttle every merchant to
  ten requests a minute.
- **per key** — `settings.merchant_api_key_rate_max` (600 per 60 s), charged
  **after** the signature verifies. A `key_id` travels in a plaintext header,
  so charging it earlier would let anyone who reads one spend its owner's
  budget; forged traffic is bounded by the IP axis instead.

Brute force is not the threat model — the secret is 256 bits and compared
with `compare_digest` — throughput is, which is what both numbers are sized
for.

## Status

Schema (M1 Task 1), the deposit service (M1 Task 3), wholesale pricing
(M1 Task 5), the admin endpoints (M1 Task 6), the admin SPA screens
(M1 Tasks 7–8), and API-key issuance plus the signed-request dependency
(M2 Task 2) are in place. The machine API's own endpoints and the cabinet
BFF land in the rest of M2+.
