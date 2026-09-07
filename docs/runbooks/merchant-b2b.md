# Runbook — Merchant B2B

Two halves. The **catalog** sections cover M1's B2B visibility flags and the
one-time launch flip. The **machine API** sections, from "The machine API"
onward, cover the `/merchant/v1` surface a reseller's server calls: onboarding,
credentials, the failure modes that need a human, and the gaps a pilot
integrator will meet.

## Catalog: verify the launch-flip after deploy (migration 0068)

`apps/api/migrations/versions/0068_catalog_b2b_flags.py` adds `visible_b2b`
to `brands`/`skus` and backfills it on deploy: every active brand of an
active, `top_up`/`voucher` SKU flips `visible_b2b = true`, except the
`steam-gifts` brand (a spec non-goal, excluded by slug).

**Do not trust the migration docstring's dev-snapshot list of brands as the
expected result on prod.** The flip runs against whatever the catalog holds
on deploy day — brands added, removed, or deactivated since this migration
was written change the outcome, and the docstring is a point-in-time example,
not a spec. Always verify against the live result:

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "SELECT slug, visible_b2b FROM brands ORDER BY visible_b2b DESC, slug;"
```

Read the output against the actual rule, not a memorized list: every row
with `visible_b2b = t` should be an active brand carrying at least one
active `top_up`/`voucher` SKU, and `steam-gifts` should be the one
otherwise-eligible brand sitting at `f`. If a brand you expected to see
flipped isn't there, check whether it (or all of its SKUs) was inactive at
deploy time — the migration only flips what was active then; it does not
re-run when a brand is reactivated later (see "Reflipping a brand" below).

## Catalog: reflipping a brand after the fact

The 0068 backfill is a one-time migration, not a standing rule — a brand
activated (or given its first active SKU) after deploy does **not**
automatically gain `visible_b2b`. The admin UI covers per-brand/per-SKU
toggles and bulk **markup** (spec §8.3); what it does not yet offer is a bulk
**visibility** action — for that, flip by hand:

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "UPDATE brands SET visible_b2b = true WHERE slug = '<brand-slug>';
   UPDATE skus SET visible_b2b = true
     FROM products
    WHERE skus.product_id = products.id
      AND products.brand_id = (SELECT id FROM brands WHERE slug = '<brand-slug>')
      AND skus.active AND products.active
      AND products.kind IN ('top_up', 'voucher');"
```

---

## The machine API (`/merchant/v1`)

Everything from here on concerns the reseller-facing API that M2 shipped. The
contract a merchant implements against is
`apps/api/src/yupay/modules/merchants/README.md`; the decisions behind it are
ADR-0068 and ADR-0069. **Read "Known gaps before a pilot integrates" at the
bottom before you put the first reseller on this.**

Admin calls below use `-H "Authorization: Bearer <admin JWT>"` — the same
admin session the SPA uses.

## Onboarding a merchant, end to end

Four steps, in this order. Steps 1–2 have SPA screens; step 3 does not yet.

### 1. Create the account

Admin SPA → **Мерчанты** → «Создать». Or:

```bash
curl -X POST "https://api.yupay.uz/api/v1/admin/merchants" \
  -H "Authorization: Bearer <admin JWT>" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Acme Resale"}'
```

Keep the returned `id`. It is the `merchant_id` every step below needs, and it
is what the merchant quotes to support.

### 2. Credit the deposit

Admin SPA → the merchant's detail page → the deposit-credit form. It mints one
`Idempotency-Key` per logical attempt and warns loudly if the response's
`amount` differs from what was typed — which is how a mistakenly reused key
becomes visible, since the ledger replays **by key without comparing
parameters**. Prefer the SPA for this. The API, if you must:

```bash
curl -X POST "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/deposit-credits" \
  -H "Authorization: Bearer <admin JWT>" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' \
  -d '{"amount":"500.00","note":"bank transfer 2026-09-07, ref 44812"}'
```

`Idempotency-Key` is **required** here (16–100 characters; `uuidgen`, or any
unique string that long). A fresh one per logical credit; the same one for
every retry of that credit.

**Ordering is not blocked on the deposit** — a merchant with a zero balance
authenticates, reads `/me` and `/catalog` fine, and only `POST /orders` refuses
with `409 insufficient_deposit`. So a merchant can be handed a key and start
integrating before any money moves.

### 3. Issue the API key

There is **no SPA screen for this yet** — it is a curl call.

```bash
curl -X POST "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/api-keys" \
  -H "Authorization: Bearer <admin JWT>" \
  -H 'Content-Type: application/json' \
  -d '{"label":"acme prod","ip_allowlist":["203.0.113.0/24"]}'
```

Both fields are optional; omit `ip_allowlist` (or send `null`) for no filter.
Entries are addresses or CIDR blocks, IPv4 or IPv6, at most 32, and a typo is
rejected at the parse boundary rather than stored to fail silently later.

The response carries `key_id` **and** `secret`. **That is the only time the
secret exists anywhere.** It is encrypted at rest under a key the database does
not hold, so nobody — including us — can read it back.

Do not pass `Idempotency-Key` on this call unless you have a reason: a replay
returns the original `key_id` with `secret: null` on purpose (the replay store
has no reaper and a usable credential must not sit in it in the clear). If you
did, and the first response was lost, revoke that key and issue another.

### 4. Hand it over, once

Send `key_id` and `secret` over a channel the merchant controls, and say in the
same message that we cannot resend it. Send with it:

- the base URL, `https://api.yupay.uz`;
- the contract: `apps/api/src/yupay/modules/merchants/README.md`, whose
  "Your first order in ten minutes" is a runnable script;
- a cheap SKU to test on — **there is no sandbox.** The first order they place
  is a real order against their real deposit.

Then confirm they are live:

```bash
curl "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/api-keys" \
  -H "Authorization: Bearer <admin JWT>"
```

`last_used_at` moving from `null` is the signal that their signing works. It is
throttled to one write a minute per key, so it lags a burst; it never lags by
more than that.

## Rotating and revoking a key

Several keys can be live at once, which is what makes rotation zero-downtime:

1. issue the new key (step 3 above);
2. the merchant deploys it and confirms traffic on the new `key_id`
   (`last_used_at`);
3. revoke the old one:

```bash
curl -X DELETE "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/api-keys/<key-id>" \
  -H "Authorization: Bearer <admin JWT>"
```

Revocation sets `revoked_at` and takes effect on the next request — there is no
cache and no grace period. It is naturally idempotent (a second call returns
the **first** timestamp, not a new one), and the key is matched on
`(merchant_id, key_id)`, so one merchant's id in the path can never revoke
another's credential — that is a 404.

**Changing an IP allowlist means rotating.** There is no endpoint that edits an
existing key's allowlist; issue a new key with the right list and revoke the
old one.

**On a suspected leak, revoke first and talk after.** A leaked secret is worth
the merchant's whole deposit balance, a signature is valid for the ±300 s
window it was made in, and there is no per-order approval step to catch a
fraudulent order after the fact.

## `INVENTORY_ENC_KEY` is now load-bearing for two subsystems

It was the voucher-code warehouse's key. It is now also the input from which
merchant API-key secrets are encrypted (`core/crypto.py` derives a separate key
per purpose by HKDF, so the two never share key material — but they share the
one input).

**If it is rotated or lost, every merchant API key stops verifying.** The
symptom is precise and worth memorising, because it does not look like an
encryption failure from the outside:

- every `/merchant/v1` request answers an ordinary `401 invalid_credentials` —
  the same body an unknown key gets, because the auth path treats an
  unopenable secret as a bad credential rather than a 500;
- the api container logs `merchant_api_key_undecryptable` with the `key_id`,
  once per request. That log line is the only way to tell this apart from a
  merchant who broke their own signing.

```bash
docker compose -f docker-compose.prod.yml logs --since 30m api \
  | grep merchant_api_key_undecryptable
```

**Recovery is revoke-and-reissue.** There is no re-encryption path: the
plaintext secrets are gone with the old key. Restore the old value of
`INVENTORY_ENC_KEY` if you still have it (the voucher warehouse needs that
anyway — the same rotation breaks every stored code); otherwise every merchant
needs a new key issued and deployed on their side, which is a conversation, not
a command.

If the variable is **empty** in prod rather than wrong, the failure is louder
and earlier: `core.crypto` raises at first use, so key issuance and
verification both 500, and `bootstrap` already logs `prod_config_incomplete` at
startup naming `INVENTORY_ENC_KEY`. Apply the secret with
`docker compose up -d`, never `restart` — `restart` reuses the container and
keeps the old `env_file` values.

See also `docs/runbooks/rotate-secrets.md`.

## The Caddy access-log redaction must be deployed

`infra/caddy/Caddyfile.prod` deletes `X-Merchant-Signature` and
`X-Merchant-Key` from the access log in **both** site blocks that keep one —
`yupay.uz` and `api.yupay.uz`. Only the second can ever see a merchant
request; the first carries the same filter so a copied log block cannot
reintroduce the leak. Caddy
redacts `Authorization` and nothing else, so without that filter every signed
request writes its credentials verbatim to stdout, promtail ships them to Loki,
and anyone with Loki read access can replay a captured request for the
remainder of its ±300 s window.

**Confirm it is live before the first merchant sends a real signature:**

```bash
docker compose -f docker-compose.prod.yml exec caddy \
  grep -c 'X-Merchant-Signature delete' /etc/caddy/Caddyfile
# 2 — one per site block that keeps an access log (yupay.uz and api.yupay.uz).
# 0 means the container is running an older file: force-recreate, below.

# Then make one signed request and confirm nothing leaked:
docker compose -f docker-compose.prod.yml logs --since 5m caddy \
  | grep -c 'X-Merchant-Signature'   # must be 0
```

**Editing `Caddyfile.prod` on the host needs `up -d --force-recreate caddy`.**
It is a single-file bind mount and `git checkout` swaps the inode out from
under the running process, so `caddy reload` re-reads the stale one and you
will believe you have deployed a change you have not:

```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate caddy
```

## The merchant channel is always asynchronous

`POST /merchant/v1/orders` forces the fulfilment queue on at the call site,
whatever `FULFILMENT_ASYNC` is set to (ADR-0069 §6, and
`docs/runbooks/fulfillment-queue.md` for the queue itself).

Two consequences for whoever is on call:

- **It depends on the worker being up, always** — not only after the flag is
  flipped. A stalled worker shows as merchant orders sitting in `fulfilling`
  with the deposit correctly debited: nothing is lost, nothing needs
  reconstructing, and nothing is delivered either.
- **Turning `FULFILMENT_ASYNC` off does not return merchant orders to inline
  fulfilment**, and must never be attempted as a way to do so. That is the
  whole point of the call-site override: inline, a supplier purchase would sit
  inside the transaction that debits the deposit.

## A merchant order stuck in `fulfilling`

Two very different situations wear the same status, and `failure_reason` on
`GET /merchant/v1/orders/{merchant_order_id}` is what separates them.

**`failure_reason` is `null` — it is genuinely in progress, or the queue is
stalled.** Nothing is wrong with the order. Check queue depth and the worker
(`docs/runbooks/fulfillment-queue.md`); a backlog can be entirely merchant
orders even with the flag off.

**`failure_reason` is `fulfillment_failed` — the delivery failed and nothing
will move the order on its own.** The order row stays `fulfilling` for good,
because only the item's `fulfillment_state` went `failed`; the status alone
would say "in progress" indefinitely. **Resolving this needs a human.** The
merchant is told to treat a non-null `failure_reason` as terminal and to
contact support quoting `order_id`, so by the time you see it they have already
stopped waiting.

Find the order:

```bash
docker compose -f docker-compose.prod.yml exec postgres psql -U yupay_app -d yupay -c \
  "SELECT o.id, o.idempotency_key AS merchant_order_id, o.status, o.created_at,
          i.unit_price_usd, i.fulfillment_state, i.sku_id
     FROM orders o JOIN order_items i ON i.order_id = o.id
    WHERE o.merchant_id = '<merchant-id>'
      AND o.idempotency_key = '<merchant_order_id>';"
```

Then either retry the fulfilment (the ordinary admin order tooling, same as a
retail order) or settle it — next section.

## There is no merchant refund path: settling a failed order by hand

**Nothing refunds a merchant order.** `refunded_usd` is `"0.00"` on every order
and will stay so until M3 posts the row. A failed supplier delivery leaves the
deposit debited, and support settles it as a **deposit credit**.

Know what that does and does not do, before you tell a merchant what to expect:

- it moves `balance_usd` on `GET /merchant/v1/me`, and appears on
  `GET /merchant/v1/transactions` as a `merchant_deposit_credit` row with a
  positive `amount_usd` and a `null` `merchant_order_id`;
- it does **not** change the failed order's `refunded_usd`, which stays
  `"0.00"`. The credit is booked against the merchant, not against the order —
  no admin surface can reference an order — so the order read will never show
  it. Say so explicitly when you tell them it is settled, or they will go
  looking for it in the wrong field.

The steps:

1. **Close the order** so it stops looking deliverable, with a reason that will
   be read by us and never by the merchant (they get the closed vocabulary
   value `order_failed`):

   ```bash
   curl -X POST "https://api.yupay.uz/api/v1/admin/orders/<order-id>/fail" \
     -H "Authorization: Bearer <admin JWT>" \
     -H 'Content-Type: application/json' \
     -d '{"reason":"supplier could not deliver; deposit credited back 2026-09-07"}'
   ```

   Legal from `paid`, `fulfilling` and `fulfilled` only, and it cancels any
   open fulfilment task. It **moves no money**.

2. **Credit the deposit** for exactly what the order charged — the
   `unit_price_usd` from the query above, which is also `price_usd` on the
   merchant's own order read. `order_items.unit_price_usd` is `NUMERIC(20, 6)`
   so psql prints it as `1.060000`; send `1.06`. (Both are accepted — the
   amount is validated on significant decimals, and a merchant price is always
   a whole cent — but the two-decimal form is what the merchant sees and what
   your `note` should quote.) Use the SPA form, or:

   ```bash
   curl -X POST "https://api.yupay.uz/api/v1/admin/merchants/<merchant-id>/deposit-credits" \
     -H "Authorization: Bearer <admin JWT>" \
     -H "Idempotency-Key: refund-<order-id>" \
     -H 'Content-Type: application/json' \
     -d '{"amount":"1.06","note":"settlement for failed order <order-id> (<merchant_order_id>)"}'
   ```

   **Key it on the order id**, as above. That is what makes a retry after a
   timeout safe: the ledger replays by key, so the same
   `Idempotency-Key: refund-<order-id>` can never credit the same failed order
   twice, however many times you run it. Put the `order_id` in the `note` as
   well — it is the only place the connection is recorded until M3.

3. **Tell the merchant**, quoting their `merchant_order_id`: the order is
   closed as `order_failed`, and the amount is back on their deposit balance,
   visible on `/transactions` — not on the order.

## Known gaps before a pilot integrates

Three things a reseller can meet on day one. None is a bug in the sense of
"something broke"; each is a decision or an omission with a price, and the
price is worth knowing before it is paid.

### 1. The ±2% drift rule gives 2% away, per order, forever

`expected_price` within ±2% of our price executes at the **lower** of the two
(spec §8.4, `pricing.price_to_charge`). `/catalog` is live-computed and never
cached, so a merchant can read the current price and always send
`current × 0.98`, taking a guaranteed 2% off wholesale on **every** order. On
the default 7% markup that is roughly a quarter of the margin, and the margin
floor does not catch it — 7% − 2% still clears the 2% floor.

The rule came from the Steam-gifts flow, where the counterparty is a human who
cannot compute that. Here it is a machine that can.

- **Cost of leaving it:** a quarter of the B2B margin, if any merchant notices.
  Nothing alerts on it; you would find it by comparing charged prices to list.
- **Fix:** one line in `pricing.price_to_charge` — `return current` for
  quote-only, or an asymmetric band that accepts a higher expectation and
  refuses a lower one. It is the owner's call; until they rule, the spec
  governs.
- **Watch for it** by comparing `order_items.unit_price_usd` against the SKU's
  computed list price on merchant orders.

### 2. Two error bodies do not conform to the published contract

The module README publishes an RFC 7807 table. Two answers on `/merchant/v1`
are not problem+json, because **there is no app-wide
`RequestValidationError` handler**: FastAPI's default fires instead and returns
`{"detail": [ … ]}` with no `type` and no `code`.

- `GET /merchant/v1/transactions?limit=0` (or anything outside 1–200);
- any `POST /merchant/v1/orders` body the schema rejects — a missing field, an
  unknown one, `expected_price` with three decimals.

- **Cost of leaving it:** an integrator whose error handling switches on `code`
  gets an unhandled shape on the two failures most likely to happen while they
  are writing their client. The README documents it, which is a warning, not a
  fix.
- **Fix:** one `app.add_exception_handler(RequestValidationError, …)` in
  `bootstrap.create_app` rendering the existing
  `https://app.yupay.uz/errors/validation` type URI. It closes both cases and
  every other surface at the same time — the storefront has the same
  non-conforming body today.

### 3. No refund path

Covered above. `refunded_usd` is `"0.00"` on every order; a failed delivery is
settled by a manual deposit credit that the order read does not show.

- **Cost of leaving it:** every failed delivery is a support ticket and a hand
  transfer, and a merchant reconciling by order rather than by statement cannot
  see the settlement at all. It scales with order volume, so it is fine for a
  pilot and not for ten merchants.
- **Fix:** M3, which adds the refund posting (the module README's posting table
  already reserves the row) and the outbound webhook. `refunded_usd` starts
  telling the truth the moment that row is posted, with no contract change.
