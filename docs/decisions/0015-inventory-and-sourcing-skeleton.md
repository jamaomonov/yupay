# 0015. Inventory warehouse + sourcing rules

- **Status**: Accepted
- **Date**: 2026-05-16
- **Builds on**: ADR-0011 (order FSM), ADR-0013 (fulfilment skeleton)
- **Deciders**: founding team
- **Tags**: backend, inventory, sourcing, fulfilment

## Context

YuPay's fulfilment strategy is **hybrid**: some SKUs we ship from a private
warehouse of pre-purchased voucher codes (bought in bulk at a discount, sitting
encrypted in our DB), others we always fetch from a supplier API. Some SKUs we
want to try the warehouse first and fall back to the supplier if stock is dry;
others we want to _force_ through one route regardless of stock (e.g. to test
a supplier integration even when our warehouse is full).

The skeleton fulfilment module currently hardcodes `supplier = "mock"` for every
order item — see [`fulfillment/service.py:_resolve_supplier`](../../apps/api/src/yupay/modules/fulfillment/service.py). We replace that with two new modules.

## Decision

Land **`inventory`** (the warehouse) and **`sourcing`** (the per-SKU routing
rule) as a paired feature. Fulfilment consults sourcing before picking a
provider; if sourcing says "use the warehouse," fulfilment calls
`inventory.reserve_and_issue` instead of a `Fulfiller`.

### `inventory` tables (migration `0010`)

```
inventory_codes
  id              UUID PK
  sku_id          UUID NOT NULL → skus.id
  code_ciphertext BYTEA NOT NULL    -- libsodium SecretBox over the cleartext code
  code_nonce      BYTEA NOT NULL    -- 24 bytes, per-row
  code_hash       CHAR(64) NOT NULL -- SHA-256(cleartext); used for dedup, never reversed
  state           VARCHAR(16) NOT NULL CHECK (state IN ('available','reserved','issued','voided'))
  order_item_id   UUID NULL → order_items.id   -- set when reserved/issued
  reserved_at     TIMESTAMPTZ
  issued_at       TIMESTAMPTZ
  voided_at       TIMESTAMPTZ
  expires_at      TIMESTAMPTZ NULL              -- optional code-expiry from the issuer
  uploaded_by     VARCHAR(64)
  created_at      TIMESTAMPTZ DEFAULT now()
  UNIQUE (sku_id, code_hash)                    -- dedupe accidental double-uploads
  INDEX  (sku_id, state) WHERE state='available' -- the hot path for reserve

inventory_uploads
  id          UUID PK
  sku_id      UUID NOT NULL → skus.id
  total       INT NOT NULL
  succeeded   INT NOT NULL
  duplicates  INT NOT NULL
  uploaded_by VARCHAR(64)
  created_at  TIMESTAMPTZ DEFAULT now()
```

### `sourcing` tables (same migration)

```
sku_sourcing_rules
  sku_id        UUID PK → skus.id
  mode          VARCHAR(24) CHECK (mode IN ('auto','force_inventory','force_supplier'))
  supplier_slug VARCHAR(32) NULL    -- required when mode='force_supplier'
  updated_at    TIMESTAMPTZ
  updated_by    VARCHAR(64)
```

Missing row = `mode='auto'` with the platform default (inventory-first,
fallback to `mock` supplier in the skeleton).

### Sourcing algorithm

```
resolve_for_sku(sku_id):
  rule = SELECT * FROM sku_sourcing_rules WHERE sku_id=?
  if rule is None or rule.mode == 'auto':
      return Decision(primary='inventory', fallback='supplier:mock', strict=False)
  if rule.mode == 'force_inventory':
      return Decision(primary='inventory', fallback=None, strict=True)
  if rule.mode == 'force_supplier':
      return Decision(primary=f'supplier:{rule.supplier_slug}', fallback=None, strict=True)
```

### `reserve_and_issue` algorithm

Race-safe atomic reservation against many concurrent fulfilment workers:

```sql
UPDATE inventory_codes
SET state='reserved', order_item_id=:item_id, reserved_at=now()
WHERE id = (
  SELECT id FROM inventory_codes
  WHERE sku_id=:sku_id AND state='available'
  ORDER BY created_at  -- FIFO; oldest codes first
  FOR UPDATE SKIP LOCKED
  LIMIT 1
)
RETURNING id, code_ciphertext, code_nonce;
```

If the UPDATE returns zero rows → `NoStockError`. The fulfilment layer decides
fallback vs. failure.

On supplier callback / immediate success the service flips `state='issued'`
and records `issued_at`. On admin revoke or order cancel: `state='voided'`.

### Encryption

- `nacl.secret.SecretBox` (XSalsa20-Poly1305, authenticated).
- 32-byte key from `INVENTORY_ENC_KEY` (base64 in env / Docker secret in prod).
- In dev, an empty key derives a deterministic dev-only key from the JWT pepper
  (so tests don't need extra setup). In prod, an empty `INVENTORY_ENC_KEY`
  refuses to start.
- The cleartext code lives in memory **only** for the duration of one
  `reserve_and_issue` call. Logs and error payloads never include it.
- Key rotation is deferred to ADR-0020; we'll add a `key_version` column then.

### Wiring into fulfilment

`fulfillment.service.process_task()` becomes:

1. Read the order item's SKU.
2. `decision = sourcing.resolve_for_sku(sku.id)`.
3. If `decision.primary == 'inventory'`:
   - Try `inventory.reserve_and_issue(sku, item)`.
   - On `NoStockError`:
     - if `decision.strict`: task fails with `no_stock`.
     - else: retry with `decision.fallback`.
   - On success: write a `Delivery` row with `artifact_kind='voucher_code'` and
     the cleartext code; mark task `succeeded`.
4. Else (supplier route): existing `Fulfiller.fulfill(...)` path.

The "supplier" recorded on the task is the _route taken_ (e.g. `inventory` or
`mock`). When real adapters land, this lets ops see at a glance whether an
order ran through stock or a third party.

### Admin endpoints

```
POST /api/v1/admin/inventory/bulk-upload
  body: { sku_id, codes: ["AAA-BBB-...", ...] }
  → { upload_id, total, succeeded, duplicates }

GET  /api/v1/admin/inventory/sku/{sku_id}
  → { available, reserved, issued, voided }

GET  /api/v1/admin/inventory/codes?sku_id=&state=&limit=
  → admin-only listing; codes are returned in cleartext (the admin is by
    definition trusted with them).

GET  /api/v1/admin/sourcing/rules
PUT  /api/v1/admin/sourcing/rules/{sku_id}
  body: { mode: 'auto'|'force_inventory'|'force_supplier', supplier_slug? }
```

No customer-facing routes. Users only see the issued voucher via the existing
`deliveries` table.

## Consequences

- Adding `inventory` as a (pseudo)provider keeps `fulfillment/service.py`
  uniform — every task records a `supplier` slug, just with two extras
  (`inventory`, plus whatever fallback ran).
- `pgcrypto`/libsodium key material is now a piece of operational state. The
  rotation runbook is added in ADR-0020.
- Bulk-upload of even small batches is rate-limited by per-row encryption
  (microseconds each). For 100k codes we'll batch + parallelise; the skeleton
  caps batch size at 5000.

## What's deferred

1. **Pre-allocated reservations** — currently we reserve at fulfilment time. A
   future optimisation: reserve at _checkout_ to guarantee stock at the price
   shown to the user. Needs an order-creation hook.
2. **Code-expiry sweeper** — a scheduled job that voids codes past `expires_at`.
3. **Key rotation** with `key_version` (ADR-0020).
4. **CSV/file upload** — for now bulk-upload is JSON only.
5. **Inventory reporting** — low-stock alerts, daily diff vs supplier price.

---

## Update — manual mode (2026-05-22)

Added a fourth `Mode` value: `"manual"`. `Decision` for it:
`primary="supplier:manual", fallback=None, strict=True`. `set_rule` forces
`supplier_slug=NULL` (the slug is implicit). Purpose: SKUs without a
supplier API — the order ends up in the admin queue
(`/admin/fulfillment/tasks?supplier=manual&status_filter=in_progress`)
where an operator completes or rejects it via the new endpoints described
in the ADR-0013 update.

Migration `0012_manual_fulfillment` relaxes
`ck_sku_sourcing_rules_mode` to allow the new value (and adds two audit
columns on `fulfillment_tasks`).
