# Merchant B2B — M2: The Machine API — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A merchant's server can integrate: authenticate with a signed
request, read its profile and priced catalog, place an order that debits its
deposit and is fulfilled by the existing pipeline, and read that order's
status and its deposit ledger. After M2 a pilot merchant is sellable — driven
through admin + support, with no cabinet yet (that is M4) and no webhooks yet
(M3).

**Architecture:** `/merchant/v1/*` — a router versioned independently of
`/api/v1`, authenticated by API key + HMAC request signature. Order creation
**reuses** `orders.service.create_order` through a new merchant `Actor` arm;
fulfilment is untouched. Pricing comes from M1's one-home functions.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic.

**Spec:** `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`
**Predecessor:** `docs/superpowers/plans/2026-09-06-merchant-b2b-m1.md` (merged at `c55c1ff`), ADR-0068

## Global Constraints

- **Do not fork the order path.** A merchant order is a normal order with a
  merchant actor, born `paid`, fulfilled by the same pipeline. Any change to
  `orders.service` must leave every retail path byte-identical — proven by
  running the full orders + payments suites, not assumed.
- **Money:** `Decimal` only, USD, serialised as strings. Deposit debit legs
  are the exact mirror of M1's credit (`C merchant_deposit / D
house_payments_received`) — the module README's posting table is the
  contract; do not re-derive directions.
- **Pricing:** only `modules/merchants/pricing.py`. No second implementation,
  no inline `cost × markup` anywhere.
- **Contract stability:** `/merchant/v1` is consumed by third-party code that
  nobody but its owner can redeploy. Breaking changes need a new version, not
  an edit. Error bodies are RFC 7807 with the documented codes.
- **PII:** merchant-supplied end-customer identifiers (player ids, logins)
  are transit-only; never in URLs, never in logs beyond the existing
  redaction. `hash_short` for anything that must be logged.
- mypy --strict, ruff, Google docstrings; migrations pair schema with their
  indices; every new endpoint gets an auth test (401 no key, 403 wrong/frozen
  merchant) against the mounted app.
- Never run `next build` on the host; `pnpm exec prettier --check .` before
  finishing any task touching TS/JSON/MD.

## Carry-overs mandated by M1's reviews (not optional)

1. **The `(merchant_id, idempotency_key)` partial UNIQUE on `orders` lands in
   Task 1, before anything leans on it.** User and guest each have one
   (`uq_orders_idem_user` / `uq_orders_idem_guest`); merchant does not, and
   `merchant_order_id` idempotency must resolve races in the database, not in
   application code.
2. **`ip_allowlist` write-path round-trip test** in Task 2 — this is the
   codebase's first `ARRAY(INET)` and only its read path was ever exercised.
3. Per-resource replay-scope suffixes on the M1 admin writes (a one-line
   change per endpoint) — fold into Task 2 while in that file.

---

### Task 1: Merchant actor in the order path (+ migration 0069)

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/service.py` (`Actor` ~:176, `_record_event` ~:187, `_existing_idempotent_order` ~:698)
- Create: `apps/api/migrations/versions/0069_orders_merchant_idempotency.py`
- Test: `apps/api/tests/integration/test_orders_merchant_actor.py` (extend), `apps/api/tests/unit/test_orders_actor.py` (new)

**Interfaces:**

- Produces: `Actor(user_id=None, email=None, merchant_id=...)` — exactly-one-of-three, mirroring the DB CHECK 0066 installed; `_record_event` labels merchant actors `merchant:{id}`;
  `_existing_idempotent_order` matches on the merchant arm.
- Produces: `uq_orders_idem_merchant` — partial UNIQUE on `(merchant_id, idempotency_key) WHERE merchant_id IS NOT NULL AND idempotency_key IS NOT NULL`, mirroring the two existing ones exactly (read them in `0006_orders_init.py` and copy the shape).

Read `core/db.py`'s naming-convention warning before naming anything.

- [x] **Step 1: failing tests**

```python
def test_actor_accepts_a_merchant_arm() -> None:
    a = Actor(user_id=None, email=None, merchant_id="m1")
    assert a.merchant_id == "m1"

def test_actor_still_rejects_two_arms() -> None:
    with pytest.raises(ValidationError):
        Actor(user_id="u1", email=None, merchant_id="m1")

def test_actor_still_rejects_zero_arms() -> None: ...

async def test_same_merchant_key_returns_the_same_order(db_session): ...
async def test_two_merchants_may_share_a_key(db_session): ...   # scoping proof
```

- [x] **Step 2: run → FAIL** (`Actor` takes no `merchant_id`)
- [x] **Step 3: implement** `Actor`, event labelling, idempotent lookup, migration
- [x] **Step 4: FULL orders + payments integration suites** — retail must not move
- [x] **Step 5: commit** `feat(api/orders): merchant actor and its idempotency scope`

---

### Task 2: API keys — issuance, and the signed-request dependency

**Files:**

- Modify: `apps/api/src/yupay/modules/merchants/{service.py,admin.py,admin_routes.py,schemas.py,api.py}`
- Create: `apps/api/src/yupay/modules/merchants/auth.py`
- Create: `apps/api/migrations/versions/0070_merchant_key_last_used.py` **only if** a column is missing — check first; M1's table may already suffice
- Test: `apps/api/tests/integration/test_merchant_api_auth.py`, extend `test_merchants_admin_routes.py`

**Interfaces:**

- Produces: `POST /admin/merchants/{id}/api-keys` → `{key_id, secret}` — **secret returned once, stored only as SHA-256**; `DELETE /admin/merchants/{id}/api-keys/{key_id}` (revoke, sets `revoked_at`); the list endpoint shows `key_id`, `label`, `last_used_at`, `revoked_at` and **never** the secret.
- Produces: `merchant_auth` FastAPI dependency → the authenticated `Merchant`.

Signature scheme (document it in the module README — third parties implement
against it):

```
X-Merchant-Key: <key_id>
X-Merchant-Timestamp: <unix seconds>
X-Merchant-Signature: hex(HMAC_SHA256(secret, f"{timestamp}\n{method}\n{path}\n{body}"))
```

- Timestamp window ±300s (reject outside — replay defence).
- `hmac.compare_digest` for both the signature and any key comparison.
- Revoked or unknown `key_id` → 401 with the same body and timing shape as a
  bad signature (do not leak which failed).
- Frozen merchant → 403 `merchant_frozen`.
- `ip_allowlist` non-null → the request IP must be in it, else 403. **Test the
  write path round-trip** (carry-over 2): store two CIDRs, read them back,
  match and non-match.
- Rate limit per merchant via the existing `guard_ip` bucket machinery — add
  a `merchant-api` bucket in config.
- On success: update `last_used_at` (cheap, best-effort — must never fail the
  request).

Also in this task (carry-over 3): give the M1 admin write endpoints
per-resource replay scopes (`f"merchants.sku_b2b:{sku_id}"` etc.).

- [x] **Step 1: failing tests** — issuance returns a secret once and the row
      stores only its hash; a correct signature authenticates; a tampered
      body, a stale timestamp, a revoked key, an unknown key, a frozen
      merchant, and a disallowed IP each fail with the right status; the
      allowlist round-trip; `last_used_at` advances.
- [x] **Step 2-4: FAIL → implement → pass**
- [x] **Step 5: commit** `feat(api/merchants): issue API keys and verify signed requests`

> No migration 0070: M1's `0065_merchants_core` already ships `last_used_at`,
> `ip_allowlist`, `revoked_at`, `label`, `key_id` (unique) and `secret_hash`.
> The rate-limit shape follows the controller's ruling, not the literal brief:
> `guard_ip(bucket="merchant-api")` with **no** `subject` (its subject axis is
> capped by one global setting), plus an explicit per-`key_id` counter on the
> single promoted `ip_guard.hit_counter`.
>
> **Revised after review (fix round 1), while zero keys existed and
> `/merchant/v1` had zero integrators — so both changes were free:**
> migration **0070** replaces `secret_hash` with `secret_enc`/`secret_nonce`
> (encrypted at rest via the new `core/crypto.py`, HKDF purpose separation
> from `INVENTORY_ENC_KEY`), which lets the HMAC be keyed by the secret
> directly with no derivation step; and the canonical string became
> `{timestamp}\n{METHOD}\n{raw_path}\n{raw_query}\n{sha256(body)}` — raw
> request-line bytes so no field boundary can be forged, the query signed, the
> body hashed. A verified signature is also single-use for the width of the
> window.

---

### Task 3: `GET /merchant/v1/me` and `GET /merchant/v1/catalog`

**Files:**

- Create: `apps/api/src/yupay/modules/merchants/machine_routes.py`, extend `schemas.py`
- Modify: `apps/api/src/yupay/api/v1/__init__.py` (or wherever the app mounts routers — mount `/merchant/v1` as its OWN prefix, not under `/api/v1`)
- Test: `apps/api/tests/integration/test_merchant_api_read.py`

**Interfaces:**

- `GET /me` → `{merchant_id, title, status, balance_usd}` (strings for money).
- `GET /catalog` → brands → products → SKUs where `visible_b2b` holds on both
  brand and SKU **and** `effective_cost` is not None, each SKU carrying
  `{sku_id, sku_code, name, price_usd, updated_at}` where `price_usd` is
  **this merchant's** price from `merchants.pricing`. One query set, no N+1
  (test asserts the query count does not scale with catalog size).
- Steam-gift SKUs must not appear (v1 non-goal) — they are excluded by
  `visible_b2b` already; assert it.

- [ ] Steps: failing tests (auth required; balance matches a credit; catalog
      shows only b2b-visible priced SKUs; price equals `merchant_price` for
      that merchant's markup; N+1 guard) → implement → pass → `make gen-api`
      → commit `feat(api/merchants): profile and priced catalog over the machine API`

---

### Task 4: `POST /merchant/v1/orders` — the money path

**Files:**

- Modify: `machine_routes.py`, `merchants/service.py`, `orders/service.py` (price override seam), `payments`/fulfilment glue as needed
- Test: `apps/api/tests/integration/test_merchant_api_orders.py`

**The one design decision this task must get right.** `create_order` prices
lines from retail SKU prices; a merchant order must be priced by
`merchants.pricing`. Do **not** fork `create_order`. Add a narrow, explicit
seam: an optional per-line unit-price override that `create_order` honours
**only when the actor is a merchant**, with a test proving a retail order
cannot inject a price through the same door. State the chosen shape in the
report.

Flow:

1. Authenticate (Task 2). Frozen → 403.
2. Resolve SKU; not `visible_b2b` or no cost → 404 `item_unavailable`.
3. Compute price via `merchants.pricing`. Compare to the request's
   `expected_price`: within ±2% ⇒ charge the **lower** of the two; outside ⇒
   `422 price_changed` carrying the current price.
4. Margin floor (`merchant_margin_floor_pct`) violated ⇒ `422 margin_floor`.
5. Insufficient deposit ⇒ `409 insufficient_deposit` **before** creating an
   order (no orphan rows).
6. Create the order (merchant actor, `merchant_order_id` as the idempotency
   key), debit the deposit, mark it `paid`, start fulfilment — all in one
   transaction, so a failure anywhere leaves neither an order nor a debit.
7. Replay: same `merchant_order_id` + same body ⇒ the existing order;
   different body ⇒ `409`.
8. **No end-customer email.** Verify what the delivery path does for an order
   with no email and make it explicitly skip rather than accidentally work;
   a merchant order must never send mail.

- [ ] **Step 1: failing tests** — the happy path end to end (deposit down by
      exactly the charged price, order `paid`, fulfilment task created);
      every error code above; the replay pair; the retail-cannot-inject-price
      test; the no-email assertion; a concurrency test (two same-key creates
      via `asyncio.gather` ⇒ one order, one debit).
- [ ] **Step 2-4: FAIL → implement → pass; FULL orders/payments/fulfilment suites**
- [ ] **Step 5: commit** `feat(api/merchants): place an order against the deposit`

---

### Task 5: `GET /merchant/v1/orders/{merchant_order_id}` and `GET /merchant/v1/transactions`

**Files:** `machine_routes.py`, `schemas.py`, `merchants/service.py`; tests alongside.

- Order read: status, timeline, the delivered artifact (**voucher code
  included here** — deliberately, because M3's webhook will not carry it),
  failure reason, refund mark. Scoped to the authenticated merchant — a test
  proves merchant B cannot read merchant A's order by id.
- Transactions: the merchant's own deposit ledger, paginated, reusing M1's
  grouped query (merchant-scoped by the authenticated identity, not a path
  param).

- [ ] Steps: failing tests (including the cross-merchant isolation pair) →
      implement → pass → `make gen-api` → commit
      `feat(api/merchants): read order status and the deposit ledger`

---

### Task 6: Contract documentation

**Files:** `apps/api/src/yupay/modules/merchants/README.md`, `docs/api/README.md`, `docs/architecture/sequence-diagrams/merchant-order.mmd`, `docs/decisions/0069-merchant-machine-api.md`, `docs/runbooks/merchant-b2b.md`

The audience is a third-party integrator, so this is a deliverable, not a
chore: the signature scheme with a worked example (including the exact string
being signed), every error code and what to do about each, the idempotency
contract, the price-drift contract, and the "first order in ten minutes"
walkthrough the spec promises. The ADR records the versioning stance
(`/merchant/v1` independent of `/api/v1`) and the price-override seam.

- [ ] Steps: write → `pnpm exec prettier --check .` → commit
      `docs(merchants): the machine API contract`

---

## Self-review notes

- Ordering: 1 → 2 (auth needs no order path, but Task 4 needs both) → 3
  (proves the auth stack on a trivial endpoint before the money path) → 4 →
  5 → 6.
- Names used consistently: `merchant_auth`, `machine_routes.py`,
  `uq_orders_idem_merchant`, error codes exactly as the spec's §9.4 lists.
- M3 (webhook outbox + SSRF hardening) and M4 (cabinet) stay out.
