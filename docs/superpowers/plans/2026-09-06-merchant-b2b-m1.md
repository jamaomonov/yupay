# Merchant B2B — M1: Schema, Deposit Ledger, Admin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The merchant entity exists end to end — schema, USD deposit on the
double-entry ledger, per-SKU B2B markup and visibility, the pricing function,
and the admin endpoints + admin SPA screens that let support run a pilot
merchant by hand. No machine API yet (that is M2).

**Architecture:** New domain module `apps/api/src/yupay/modules/merchants/`
per the repo's module layout. Deposit rides the existing wallet ledger
(`NORMAL_SIDE`, `post()`), mirroring the wallet gateway's posting directions.
Orders gain a third actor arm. Catalog gains `visible_b2b` + `b2b_markup_pct`.

**Tech Stack:** FastAPI + SQLAlchemy 2 async + Alembic; Vite/React admin SPA.

**Spec:** `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`

## Global Constraints

- Money: `Decimal` everywhere, USD; API serialises as strings. Never floats.
- Coverage: this touches `wallet` postings ⇒ ≥ 95% on the new ledger code.
- mypy --strict, ruff, Google docstrings; no `Any` without a justifying comment.
- Every Alembic migration pairs schema + the indices its queries need.
- Admin SPA strings: ru/en/uz in `packages/i18n` in the same PR (CI-gated).
- **Ledger convention wins over the spec's posting table.** In this repo
  `user_wallet`/`partner_*` are **debit-normal** (`NORMAL_SIDE`), and the
  wallet gateway charges `C user_wallet / D house_payments_received`,
  refunds the mirror. `merchant_deposit` follows identically (see Task 3).
  The spec's §7 table is conceptual; directions here are binding.
- The B2B-visibility semantics of the existing `active` flags: `active` IS
  retail visibility (it already gates the storefront). We do NOT rename it;
  we add `visible_b2b` beside it and document the pairing. (Spec §6's
  "visible_retail" == today's `active`.)
- Never run `next build` on the host. Run `pnpm exec prettier --check .`
  before finishing any task that touches TS/JSON/MD.

## File structure

```
apps/api/src/yupay/modules/merchants/
├── __init__.py
├── api.py            # public interface of the module (M1: service re-exports)
├── models.py         # Merchant, MerchantUser, MerchantApiKey
├── service.py        # create/freeze, deposit credit, balance
├── pricing.py        # effective_cost, merchant_price, margin floor
├── admin.py          # admin-facing service ops (bulk markup, visibility)
├── admin_routes.py   # /api/v1/admin/merchants/*
├── schemas.py
└── README.md
apps/api/migrations/versions/0065_merchants_core.py
apps/api/migrations/versions/0066_orders_merchant_actor.py
apps/api/migrations/versions/0067_catalog_b2b_flags.py
apps/admin/src/features/merchants/   # list, detail, deposit credit
```

---

### Task 1: Merchant schema (models + migration 0065)

**Files:**

- Create: `apps/api/src/yupay/modules/merchants/{__init__.py,models.py,api.py,README.md}`
- Create: `apps/api/migrations/versions/0065_merchants_core.py`
- Test: `apps/api/tests/unit/test_merchants_models.py`

**Interfaces:**

- Produces: `Merchant`, `MerchantUser`, `MerchantApiKey` mapped classes,
  importable as `from yupay.modules.merchants.models import Merchant, ...`.

Model the three tables exactly as spec §6, following
`modules/affiliate/models.py`'s style (UUID-as-str PKs via `yupay.core.ids`,
`CITEXT` emails, timezone-aware timestamps):

- `merchants`: `id`, `title: String(128) NOT NULL`,
  `status: String(16) NOT NULL server_default 'active'` +
  `CheckConstraint("status IN ('active','frozen')", name="ck_merchants_status_known")`,
  `markup_adjustment_pp: Numeric(5,2) NULL` (dormant, comment: "per-merchant
  markup adjustment in percentage points; NULL in v1, see spec §8.3"),
  `created_at`.
- `merchant_users`: `id`, `merchant_id FK merchants.id ON DELETE CASCADE`,
  `email CITEXT NOT NULL UNIQUE`, `password_hash String(256) NOT NULL`,
  `email_confirmed_at DateTime NULL`, `timezone String(64) NOT NULL
server_default 'Asia/Tashkent'`, `created_at`. Index on `merchant_id`.
- `merchant_api_keys`: `id`, `merchant_id FK ON DELETE CASCADE`,
  `key_id String(48) NOT NULL UNIQUE` (prefix `ypm_`),
  `secret_hash String(64) NOT NULL` (SHA-256 hex; comment: high-entropy
  random, not a human password — no slow hash needed),
  `label String(64) NOT NULL server_default ''`,
  `ip_allowlist: ARRAY(INET) NULL` (NULL = filter off),
  `last_used_at DateTime NULL`, `revoked_at DateTime NULL`, `created_at`.
  Index on `merchant_id`.

`README.md`: module purpose, the acquirer-vs-reseller "merchant" terminology
note verbatim from spec §3, link to the spec.

- [ ] **Step 1: failing test** — `test_merchants_models.py`:

```python
def test_merchant_status_constraint_names_are_stable() -> None:
    """Pin table/constraint names the later migrations and admin depend on."""
    assert Merchant.__tablename__ == "merchants"
    names = {c.name for c in Merchant.__table__.constraints}
    assert "ck_merchants_status_known" in names

def test_api_key_key_id_is_unique() -> None:
    cols = MerchantApiKey.__table__.columns
    assert cols["key_id"].unique
    assert cols["secret_hash"].type.length == 64
```

- [ ] **Step 2: run** `uv run pytest tests/unit/test_merchants_models.py -q` → FAIL (module missing)
- [ ] **Step 3: implement** models + empty `api.py` re-export + README
- [ ] **Step 4: migration** — copy the head-revision chaining pattern from
      `0063_steam_links.py`; create the three tables + indices. Run
      `make migrate` against the dev stack; then `alembic downgrade -1` +
      re-upgrade to prove reversibility.
- [ ] **Step 5: tests pass; `uv run ruff check` + `uv run mypy apps` clean**
- [ ] **Step 6: commit** `feat(api/merchants): merchant, user and API-key schema`

---

### Task 2: Orders third actor arm (migration 0066)

**Files:**

- Modify: `apps/api/src/yupay/modules/orders/models.py` (~:35-45, :129-133)
- Create: `apps/api/migrations/versions/0066_orders_merchant_actor.py`
- Test: `apps/api/tests/integration/test_orders_merchant_actor.py`

**Interfaces:**

- Produces: `Order.merchant_id: str | None`; constraint
  `ck_orders_actor_exclusive` now "exactly one of user_id / guest_email /
  merchant_id".

The check becomes (SQL, both in the model and migration):

```sql
(CASE WHEN user_id IS NULL THEN 0 ELSE 1 END
 + CASE WHEN guest_email IS NULL THEN 0 ELSE 1 END
 + CASE WHEN merchant_id IS NULL THEN 0 ELSE 1 END) = 1
```

Migration: `op.add_column` (`merchant_id UUID NULL` + FK to merchants ON
DELETE RESTRICT — merchant orders are financial history, a merchant with
orders must be frozen, not deleted) + partial index
`ix_orders_merchant_created ON orders (merchant_id, created_at DESC) WHERE
merchant_id IS NOT NULL` (mirrors `ix_orders_user_created`), then drop + re-add
the constraint under its existing name.

- [ ] **Step 1: failing tests** (integration, testcontainers):

```python
async def test_a_merchant_order_needs_no_user_and_no_guest_email(db_session): ...
    # insert order with merchant_id only -> commits

async def test_two_actors_still_rejected(db_session): ...
    # user_id + merchant_id -> IntegrityError

async def test_zero_actors_still_rejected(db_session): ...
```

- [ ] **Step 2: FAIL** (column missing)
- [ ] **Step 3: implement** model + migration; verify downgrade restores the
      two-arm check and drops the column.
- [ ] **Step 4: run the FULL orders + payments integration suites** — this
      constraint underpins every purchase; nothing may regress.
- [ ] **Step 5: commit** `feat(api/orders): merchants become a third order actor`

---

### Task 3: Deposit on the ledger

**Files:**

- Modify: `apps/api/src/yupay/modules/wallet/service.py` (NORMAL_SIDE)
- Create: `apps/api/src/yupay/modules/merchants/service.py`
- Test: `apps/api/tests/integration/test_merchant_deposit.py`

**Interfaces:**

- Produces:
  - `NORMAL_SIDE["merchant_deposit"] = "D"` (debit-normal, exactly like
    `user_wallet` / `partner_balance`), account owned by
    `owner_type="merchant", owner_id=<merchant_id>, currency="USD"`.
  - `merchants.service.credit_deposit(db, *, merchant_id, amount: Decimal, actor: str, idempotency_key: str, note: str | None) -> WalletTransaction`
  - `merchants.service.deposit_balance(db, *, merchant_id) -> Decimal`
  - `merchants.service.create_merchant(db, *, title) -> Merchant`
  - `merchants.service.set_status(db, *, merchant_id, status) -> Merchant`

Postings (mirror `payments/gateways/wallet.py`; comment each leg the same way):

| Event                  | Legs                                             |
| ---------------------- | ------------------------------------------------ |
| Support credits top-up | `D merchant_deposit / C house_payments_received` |
| (M2) order charge      | `C merchant_deposit / D house_payments_received` |
| (M2) refund on failure | `D merchant_deposit / C house_payments_received` |

Only the first is implemented in M1; the table goes into the module README so
M2 does not re-derive it. `credit_deposit` posts through `wallet.service.post`
with `kind="merchant_deposit_credit"` and the caller's idempotency key —
replay returns the same transaction (post() already guarantees it).

- [ ] **Step 1: failing tests**, the money-path set:

```python
async def test_credit_shows_up_in_balance(...)          # 100.00 -> balance 100.00
async def test_credit_is_idempotent_by_key(...)         # same key twice -> one tx, balance once
async def test_two_concurrent_credits_both_land(...)    # different keys, asyncio.gather -> sum
async def test_frozen_merchant_can_still_be_credited(...)  # freezing blocks ORDERS (M2), not money in
async def test_balance_of_unknown_merchant_is_zero(...)
```

- [ ] **Step 2: FAIL** → **Step 3: implement** → **Step 4: pass + the whole
      wallet test suite stays green** (NORMAL_SIDE change touches shared code)
- [ ] **Step 5: commit** `feat(api/merchants): USD deposit on the double-entry ledger`

---

### Task 4: Catalog B2B flags (migration 0067)

**Files:**

- Modify: `apps/api/src/yupay/modules/catalog/models.py` (Brand ~:93, Sku ~:323)
- Create: `apps/api/migrations/versions/0067_catalog_b2b_flags.py`
- Test: `apps/api/tests/integration/test_catalog_b2b_flags.py`

**Interfaces:**

- Produces: `Brand.visible_b2b: bool` (server_default false),
  `Sku.visible_b2b: bool` (server_default false),
  `Sku.b2b_markup_pct: Decimal` (Numeric(5,2), NOT NULL, server_default '7').

Data migration inside 0067: flip `visible_b2b = true` for every **currently
active** brand of kind top-up/voucher and their active SKUs (spec launch
decision) — vouchers/top-ups only; gift/`steam-gift` brands stay false.
Retail behaviour must not change: `active` keeps its exact meaning, and a
comment on both models records "active == retail visibility; visible_b2b is
the merchant-catalog gate; effective B2B visibility = brand.visible_b2b AND
sku.visible_b2b" (spec §6).

- [ ] **Step 1: failing tests:**

```python
async def test_new_brand_defaults_to_b2b_hidden(...)
async def test_markup_default_is_seven_percent(...)     # Decimal("7")
async def test_migration_flipped_existing_topup_brands(...)  # seeded active brand -> true
```

- [ ] **Step 2-4: FAIL → implement → pass**; run the catalog + storefront
      integration suites to prove retail listings are byte-identical.
- [ ] **Step 5: commit** `feat(api/catalog): per-surface visibility and B2B markup on SKUs`

---

### Task 5: Pricing functions

**Files:**

- Create: `apps/api/src/yupay/modules/merchants/pricing.py`
- Modify: `apps/api/src/yupay/core/config.py` (one setting)
- Test: `apps/api/tests/unit/test_merchant_pricing.py`

**Interfaces:**

- Produces (all pure, all `Decimal`):
  - `effective_cost(sku) -> Decimal | None` — reads `sku.cost_usdt`; `None`
    ⇒ not sellable B2B. (Gifts are out of v1; when they join, THIS is the
    only function that learns about live regional cost — say so in its
    docstring, citing spec §8.2.)
  - `merchant_markup_pct(sku, merchant) -> Decimal` —
    `sku.b2b_markup_pct + (merchant.markup_adjustment_pp or 0)`.
  - `merchant_price(cost: Decimal, markup_pct: Decimal) -> Decimal` —
    `ceil_to_cent(cost * (1 + markup_pct/100))`, ceiling via
    `quantize(Decimal("0.01"), rounding=ROUND_CEILING)`.
  - `violates_margin_floor(cost, price, floor_pct: Decimal) -> bool`.
  - Setting: `merchant_margin_floor_pct: Decimal = Field(default=Decimal("2"))`.

One home: nothing else in the codebase may reimplement this formula — the
docstring says so, citing this plan (the `uzsWord` lesson).

- [ ] **Step 1: failing tests** — the table that matters:

```python
@pytest.mark.parametrize(("cost","markup","expected"), [
    ("8.40", "6",  "8.91"),   # spec's worked example
    ("0.10", "7",  "0.11"),   # ceil protects margin on cheap SKUs (0.107 -> 0.11)
    ("1.00", "0",  "1.00"),   # zero markup is representable...
])
def test_price_table(...): ...
def test_floor_catches_a_fat_fingered_markup(): ...   # cost 10, markup 0.5 (typo for 5), floor 2 -> violated
def test_none_cost_means_not_sellable(): ...
def test_adjustment_pp_lowers_the_markup(): ...       # 7 + (-2) -> 5
```

- [ ] **Step 2-4: FAIL → implement → pass** (mypy strict: everything `Decimal`, no float literals)
- [ ] **Step 5: commit** `feat(api/merchants): the one pricing function`

---

### Task 6: Admin endpoints

**Files:**

- Create: `apps/api/src/yupay/modules/merchants/{admin.py,admin_routes.py,schemas.py}`
- Modify: `apps/api/src/yupay/api/v1/__init__.py` (mount under the existing admin router pattern)
- Test: `apps/api/tests/integration/test_merchants_admin_routes.py`

Endpoints (admin-auth like the other `/admin/*` routers; every write takes
`Idempotency-Key` per §9 — these DO mutate):

- `POST /admin/merchants` (title) · `GET /admin/merchants` (with USD balance
  joined) · `POST /admin/merchants/{id}/freeze|unfreeze`
- `POST /admin/merchants/{id}/deposit-credits` (amount, note) → posts via
  Task 3; response carries the new balance.
- `PATCH /admin/catalog/skus/{id}/b2b` (markup_pct?, visible_b2b?)
- `POST /admin/catalog/b2b/bulk-markup` (brand_slug | category, markup_pct) —
  the "set all vouchers to 5%" one-action bulk (spec §8.3); returns affected count.
- `PATCH /admin/catalog/brands/{id}/b2b` (visible_b2b).

- [ ] **Step 1: failing tests** — happy path per endpoint plus: admin token
      required (401 otherwise), idempotent deposit credit replay, bulk markup
      touches only the named brand's SKUs, freeze blocks nothing in M1 but
      persists status.
- [ ] **Step 2-4: FAIL → implement → pass; `make gen-api`** (openapi + TS client — admin SPA consumes it)
- [ ] **Step 5: commit** `feat(api/admin): run a merchant by hand — create, credit, markup, visibility`

---

### Task 7: Admin SPA — Merchants screens

**Files:**

- Create: `apps/admin/src/features/merchants/{MerchantsPage.tsx,MerchantDetail.tsx,api.ts,MerchantsPage.test.tsx,MerchantDetail.test.tsx}`
- Modify: admin router/nav registration (follow `features/fx` precedent)
- Modify: `packages/i18n/locales/{ru,en,uz}/admin.json`

List (title, status, balance, created); create dialog; detail: freeze toggle
with confirm, deposit-credit form (amount + note, **shows the resulting
balance from the response**, disables double-submit while in flight), ledger
of that merchant's transactions. Follow `features/fx`'s query/mutation and
test patterns (jsdom RTL — the admin app renders in tests).

- [ ] Steps: failing RTL tests (list renders balances; credit posts and
      refreshes the shown balance; freeze asks for confirmation) → implement
      → suite + `tsc` + eslint + i18n parity → commit
      `feat(admin/merchants): create, freeze and credit merchants`

---

### Task 8: Admin SPA — B2B fields on catalog screens

**Files:**

- Modify: the existing SKU editor + brand editor under `apps/admin/src/features/catalog/` (find via `grep -r "cost_usdt" apps/admin/src`)
- Modify: `packages/i18n/locales/{ru,en,uz}/admin.json`
- Test: alongside, RTL

Add: `visible_b2b` switch on brand + SKU, `b2b_markup_pct` numeric field on
SKU, and a bulk-markup action on the brand page ("наценка всем SKU бренда")
wired to Task 6's bulk endpoint. Show the computed B2B price preview next to
the markup field (`cost × (1+markup)`, ceil) so the operator sees the effect
before saving — reuse the exact constant 0.01-ceiling client-side ONLY for
preview, labelled «предварительно»; the server remains the authority.

- [ ] Steps: failing tests → implement → suites/typecheck/lint/i18n parity →
      commit `feat(admin/catalog): B2B visibility, markup and price preview`

---

## Self-review notes

- Task ordering: 1 → 2 (FK needs `merchants`), 3 → 6 (routes call service),
  4 → 5 (pricing reads the new column), 6 → 7/8 (SPA needs endpoints + client).
- Spec §6 "planned first" for the orders migration is satisfied — it is the
  first thing after the table it references.
- Names used consistently: `merchant_deposit`, `visible_b2b`,
  `b2b_markup_pct`, `markup_adjustment_pp`, `ck_orders_actor_exclusive`.
- M2 (machine API), M3 (webhooks/SSRF), M4 (cabinet app) are separate plans.
