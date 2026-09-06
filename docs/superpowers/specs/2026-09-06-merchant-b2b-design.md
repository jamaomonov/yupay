# Merchant B2B (Reseller API) — Design

**Date:** 2026-09-06
**Status:** final draft for owner review
**Shaped by:** an owner-led brainstorm, 2026-09-06. Every decision below marked
_(owner)_ was made explicitly by the owner; the rest is engineering that follows
from them.

## 1. Context and goal

Third-party resellers (merchants) buy our digital goods programmatically at a
markup over our cost and resell them under their own brand. Anyone can
register and browse the wholesale catalog; spending money requires a deposit
credited by support. YuPay is itself a client of several such APIs (G-Engine,
G2B, Waxpeer), and this design deliberately builds the supplier we wish we
had, avoiding the failure modes we have personally paid for: no client order
id, dishonest validators, missing webhook logs, secrets in URLs.

## 2. Non-goals (v1)

- **Multi-supplier aggregation / cost routing / scoring** _(owner)_. Sourcing
  stays exactly as it is. Cost is read through one function (§8.2) so a later
  aggregation project swaps an implementation, not this contract.
- **Steam gifts** _(owner)_. v1 sells top-ups and vouchers only. Gifts (async
  bot-invite delivery, regions, irreversibility) join in a later phase.
- **Test/sandbox mode** _(owner)_. Merchants debug on small live orders; the
  integration guide recommends a cheap SKU, and the launch catalog must
  contain one.
- **Low-balance notifications from us** _(owner)_. The merchant polls
  `GET /merchant/v1/me` and watches their own balance.
- Self-serve USDT deposit top-up (support credits it; the `crypto` provider
  slot in `LOGICAL_PROVIDERS` is the later path).
- Per-merchant negotiated rates in the UI. The schema carries a dormant
  per-merchant adjustment (§8.3) for a future high-volume deal _(owner)_;
  nothing exposes it in v1.
- Teams/roles inside a merchant account; TOTP 2FA (schema slot only, phase 2).

## 3. Naming and terminology _(owner)_

| Thing                  | Name                                                        |
| ---------------------- | ----------------------------------------------------------- |
| Public site + cabinet  | `apps/merchant`, served at **`reseller.yupay.uz`**          |
| Backend domain module  | `modules/merchants`                                         |
| Machine API (external) | **`/merchant/v1/*`** — versioned independently of `/api/v1` |
| Cabinet BFF (internal) | `/api/v1/merchant-cabinet/*`                                |

Checked: the only existing "merchant" route is Payme's webhook
(`/api/v1/payments/payme/merchant`) — different tree, no clash. Terminology
note for the module README: acquirers call **us** the merchant (Click/Payme
`merchant_id` credentials); in this module the merchant is the reseller. The
machine API and the cabinet BFF share neither prefixes nor auth, so the twin
paths cannot be confused in code or in Caddy.

## 4. Actors and surfaces

| Actor               | Surface                        | Auth                                                                                 |
| ------------------- | ------------------------------ | ------------------------------------------------------------------------------------ |
| Merchant's server   | `/merchant/v1/*`               | API key id + HMAC-SHA256 request signature                                           |
| Merchant's operator | Cabinet at `reseller.yupay.uz` | Email + password + **email confirmation** _(owner)_; separate `merchant_users` table |
| Our admin / support | Existing admin SPA             | Existing admin auth                                                                  |

The three credential planes are disjoint: a storefront buyer token, a merchant
cabinet session, and an API key are pairwise non-interchangeable (separate
principals and token audiences), each pinned by an authorization test — the
existing "a partner token is not a buyer token" precedent extended.

## 5. Architecture

```
apps/merchant (Next.js: SSR landing + client cabinet) ──session──▶ /api/v1/merchant-cabinet/*
merchant's server ────────────────────────────────────── HMAC ───▶ /merchant/v1/*
                         apps/api · modules/merchants/
                         ├ api.py       (machine API router)
                         ├ cabinet.py   (cabinet BFF router)
                         ├ service.py   (pricing, deposit, keys, registration)
                         └ models.py
              ledger (merchant_deposit) · catalog (visibility flags) · fulfilment (untouched)
```

- `apps/merchant` is Next.js (the landing needs SEO — «купить оптом …» is
  search traffic); infra copies the `partners` precedent: own container, Caddy
  site block, CI build target.
- **Fulfilment is untouched.** A merchant order is a normal order flagged
  merchant-owned, paid from the deposit synchronously at creation (the wallet
  gateway precedent: settled inside intent creation, `intent_url = null`).
  Delivery, retries, reconcile, refund-on-failure — all shared with retail.

## 6. Data model

- `merchants`: id, title, status (`active`/`frozen`), `markup_adjustment_pp
Decimal | null` (dormant, §8.3), created_at.
- `merchant_users`: id, merchant_id FK, citext email UNIQUE, password hash,
  email_confirmed_at, timezone (IANA string, default `Asia/Tashkent`),
  created_at. One user per merchant in v1; the FK already permits more.
- `merchant_api_keys`: id, `merchant_id`, `key_id` (public, `ypm_`-prefixed),
  secret_hash (SHA-256 — the secret is high-entropy random, not a human
  password), label, ip_allowlist (inet[], null = off), last_used_at,
  revoked_at.
- `merchant_webhooks`: merchant_id, url, secret (independent of API secrets),
  disabled_at, failure streak counters.
- `merchant_webhook_deliveries`: the outbox (§10) — also the cabinet's log.
- **Orders: a third actor arm** — `merchant_id` nullable FK; the existing
  exactly-one-of check (`user_id XOR guest_email`) becomes exactly-one-of-three.
  This is a core-table migration and is **planned first** (rollout M1).
- **SKU:** `b2b_markup_pct Decimal NOT NULL DEFAULT 7` _(owner)_.
- **Brand and SKU visibility:** the single "enabled" notion splits into two
  independent flags, `visible_retail` and `visible_b2b`, on **both** brand and
  SKU (effective = brand AND sku) _(owner)_. The storefront filters the first,
  the B2B catalog the second; a brand can be merchant-only or retail-only.
  Launch: all current top-up/voucher brands get `visible_b2b = true`.

## 7. Money: the deposit

- Account kind `merchant_deposit`, **currency USD** (USDT ≈ USD; supplier
  costs are USD; zero FX inside the loop — the merchant handles their own
  retail currency).
- Postings on the existing double-entry ledger:

| Event                          | Posting                                        |
| ------------------------------ | ---------------------------------------------- |
| Support credits a top-up       | `D house_usdt_in / C merchant_deposit`         |
| Order created                  | `D merchant_deposit / C house_b2b_revenue`     |
| Order reaches terminal failure | reverse of the above (automatic)               |
| Post-delivery dispute upheld   | same reverse, admin-triggered, reason required |
| Offboarding payout             | `D merchant_deposit / C house_usdt_out`        |

- **Debit at creation, auto-refund on terminal failure** _(owner)_. No
  reserve/settle two-phase: fulfilment already drives every order to a
  terminal status, and the ledger's balance-is-the-account invariant prevents
  concurrent overdraw.
- Cabinet «запросить пополнение» creates a support request with the amount;
  support confirms USDT receipt and credits via admin — formalising the
  current manual process _(owner)_.
- **Offboarding:** remaining deposit refundable in USDT via support; the
  written policy (fees, minimum, timing) ships with the B2B offer (§12).

## 8. Pricing _(owner-revised)_

### 8.1 Formula, in one home

```
price = ceil_to_cent( effective_cost(sku) × (1 + (sku.b2b_markup_pct + (merchant.markup_adjustment_pp ?? 0)) / 100) )
```

One function consumed by all four callers — machine-API catalog, order
pricing, cabinet display, CSV export — never copied (the `uzsWord` lesson).
Rounding is **always up, to the cent**: rounding down erases margin on cheap
SKUs invisibly. All prices are USD `Decimal`, serialised as strings.

### 8.2 Cost

`effective_cost(sku) -> Decimal | None` reads `skus.cost_usdt`. `None` ⇒ the
SKU is excluded from the B2B catalog and orders for it are rejected — never
sold at a garbage price. Admin report: "visible_b2b but no cost."

### 8.3 Markup _(owner)_

- **Per-SKU, uniform for every merchant** — prices are public to registered
  merchants, so they must be uniform. Default **7%**; admin edits per SKU.
- **Admin bulk-edit by category/brand** (storage stays per-SKU): "set all
  vouchers to 5%" must be one action, not forty clicks.
- **No global markup knob.** The only global pricing control is the **margin
  floor**: if `price < cost × (1 + floor)` the order is rejected with a
  distinct code — catches a fat-fingered per-SKU value (0.7 for 7) and cost
  spikes.
- Dormant: `merchants.markup_adjustment_pp` (e.g. −2pp for a negotiated
  giant), applied uniformly to every SKU's markup for that merchant. Not
  exposed in v1.
- **Pre-launch task:** pull the actual retail margin by category from the
  production DB and set per-category markup defaults from it, so wholesale
  never exceeds retail anywhere _(owner)_.

### 8.4 Drift and fixing

- `POST /merchant/v1/orders` requires `expected_price`. Drift ≤ ±2% ⇒ execute
  at the **lower** of the two. Beyond ⇒ `422 price_changed` carrying the
  current price (the proven Steam-gifts pattern).
- From creation the price is **fixed**; whatever fulfilment costs us is our
  problem, not the merchant's.
- The price-list endpoint carries `updated_at` per row; merchants poll. No
  price webhooks.

### 8.5 Snapshots

Each merchant order stores cost-at-creation, price-charged, and (after
fulfilment) the actual supplier price (`supplier_price_usd`, already
customer-hidden). Realised margin per merchant is an admin query; disputes are
settled by snapshot, not log archaeology.

## 9. Machine API `/merchant/v1`

### 9.1 Endpoints

| Endpoint                                      | Notes                                                                             |
| --------------------------------------------- | --------------------------------------------------------------------------------- |
| `GET /merchant/v1/me`                         | merchant profile + live deposit balance _(owner)_                                 |
| `GET /merchant/v1/catalog`                    | brands/products/SKUs visible_b2b, with this-merchant prices, `updated_at` per row |
| `POST /merchant/v1/orders`                    | body: `merchant_order_id`, `sku_id`, `expected_price`, `fulfillment_data`         |
| `GET /merchant/v1/orders/{merchant_order_id}` | status, timeline, voucher code when delivered                                     |
| `GET /merchant/v1/transactions`               | deposit ledger page (credits, debits, refunds)                                    |
| `POST /merchant/v1/validate/…`                | only where truthful (existing player-check providers); never a fake approver      |

### 9.2 Auth and integrity

- Key pair: public `key_id` + secret shown once, stored hashed. Several live
  keys per merchant (zero-downtime rotation); **regenerate** = new secret
  issued, old invalidated immediately, cabinet warns _(owner)_.
- Every request: `HMAC-SHA256(secret, timestamp + method + path + body)` in a
  header, timestamp within ±5 min, `hmac.compare_digest` verification.
- Optional per-key IP allowlist _(owner)_.
- Identifiers, keys and signatures travel in bodies/headers only — never in
  URLs (the edge access log records query strings verbatim; formalised in
  `pii-handling.md`). Signature/authorization headers join the log redactor's
  key list.

### 9.3 Idempotency

`merchant_order_id` (unique per merchant, DB constraint) **is** the
idempotency key for order creation: same id + same body ⇒ the existing order;
same id + different body ⇒ `409`. Races resolve in the constraint, not in
code. This is the client-order-id G-Engine lacks, whose absence forced our
adopt-don't-rebuy machinery — we do not pass that pain on.

### 9.4 Errors

RFC 7807, distinct codes: `insufficient_deposit`, `price_changed` (+ current
price), `item_unavailable`, `margin_floor`, `merchant_frozen`, `validation`.

### 9.5 Order lifecycle specifics

- A merchant order is **born `paid`** — it never passes `pending_payment` and
  is invisible to the 10-minute expiry job.
- **No end-customer emails.** We do not hold the merchant's customer's email
  and must not accept one; delivery is exclusively API/webhook. The
  fulfilment→email path explicitly skips merchant orders.
- Merchant-passed end-customer identifiers (player ids, logins) get the same
  log-redaction treatment as retail buyers'; transit only.

## 10. Webhooks

- Cabinet field, labeled exactly: **«Исходящий вебхук — при изменении статуса
  заказа наши серверы отправляют подписанный POST на этот URL»** _(owner)_.
- Event types (v1, complete list): `order.status_changed`,
  `balance.credited` _(owner — `balance.low` deliberately dropped)_.
- **Outbox on the existing Postgres-queue pattern** (table + claimable status,
  drained by `apps/worker` per ADR-0064): retries with backoff, auto-disable
  after a sustained failure streak (with an email to the merchant), and a
  per-delivery log (response code, attempts, body) shown in the cabinet.
- Signed with the webhook secret (independent of API secrets) + timestamp;
  docs carry a verification snippet.
- **Voucher codes never ride in webhook bodies** — the webhook says
  `delivered`, the merchant fetches the code via the authenticated GET.
  Webhook receivers get logged wholesale on the merchant's side; a code in
  their nginx log is our leak.
- **SSRF hardening** (the worker lives in the Docker network beside Postgres,
  Redis and MinIO): https only; resolve and reject private/loopback/link-local
  ranges **at connect time** (not at save time — DNS rebinding); redirects not
  followed; response size and time capped. Tests required.

## 11. Cabinet (`apps/merchant` at `reseller.yupay.uz`)

Public landing: category showcase, "cost + markup" pitch, three integration
steps, docs linked before signup, CTA to support/Telegram. Registration is
open _(owner)_: email + password + confirmation; a fresh merchant sees the
full B2B catalog and prices immediately; ordering starts when support credits
their first deposit — the money step is the KYC filter.

| Section      | Contents                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| ------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Dashboard    | balance; today: orders/success/spend; recent orders                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| Каталог      | _(owner, modeled on the G-Engine B2B portal we buy from)_ a storefront, not a table: sidebar sections per category (Топапы · Ваучеры), each opening a grid of **brand cards** with cover art and «от $X»; clicking a brand opens its page — denominations with the merchant's price and the crossed-out retail price, the same `fulfillment_data` fields the API takes, and a summary card that **creates the order right there** (price, deposit now, deposit after, «Создать заказ»). No separate products table and no separate manual-order screen: browsing and ordering are one flow. Orders placed this way debit the deposit like any API order, go through the same pricing/validation path, and the BFF mints `manual-<uuid>` as the `merchant_order_id`, so idempotency and history stay uniform — this doubles as the no-code first purchase. Per-SKU API ids shown on the brand page; CSV/JSON price export stays on the catalog |
| Заказы       | filters, search by `merchant_order_id` / our id; detail: timeline, code reveal, failure reason, refund mark                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| Транзакции   | deposit ledger, CSV statement, «запросить пополнение»                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| Настройки    | API keys (create / **regenerate** / revoke, last-used), per-key IP filter, **timezone picker** (IANA list: Asia/Tashkent, Asia/Almaty, Asia/Dubai, Europe/Moscow, Europe/London, UTC, …) — display-only: the API always speaks ISO 8601 UTC, the cabinet converts on render _(owner)_; webhook URL + secret + «send test event»                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| Документация | OpenAPI-generated reference + «первый заказ за 10 минут»; recommends the cheap debug SKU                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| Вебхуки      | delivery log: code, attempts, body                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

Email notifications to the merchant user on security-relevant changes only:
key created/regenerated/revoked, webhook URL changed.

**Localization** _(owner)_: the whole app — landing and cabinet — ships in
**ru/en/uz** via the shared `packages/i18n` catalogs (new `merchant`
namespace), under the same rule as every other surface: all three locales in
the same PR, CI fails on a missing key. The landing is localized per route for
SEO. API and webhook payloads are locale-free (machine strings, ISO 8601 UTC).

**Theming** _(owner)_: dark **and** light themes. Dark is the default and
follows the storefront palette; tokens are defined theme-agnostically from day
one — the storefront's CSS-variable approach — so light is a token swap, not a
second stylesheet. The toggle lives in the cabinet header; the choice persists
per user.

**Landing copy rules** _(owner)_: professional, SEO-oriented, and free of
internal mechanics — no pricing formulas («себестоимость + наценка»), no
process details («депозит через поддержку»), and **no delivery-time promises**
anywhere on the surface; say «автоматическая выдача» instead. Facts shown as
numbers are brand counts, not SKU counts.

## 12. Admin, abuse, legal

- Admin: create/freeze merchant, credit deposit (support-request queue), edit
  per-SKU markup with bulk-by-category/brand, visibility flags, margin
  dashboard from §8.5 snapshots, dispute refund with mandatory reason.
- **No "orders allowed" toggle** _(owner)_: a funded deposit is the gate.
  Protections: per-merchant rate limits on every endpoint (stricter on
  `validate/*` — it spends supplier quota), a sliding-window cap on the failed
  share of orders (auto-pause + notify; refund-on-failure must not become a
  free retry cannon), and the admin freeze button.
- **Legal:** a separate B2B offer/terms document (the retail offer does not
  cover merchants): dead-code claim window and evidence rules, refund policy,
  offboarding payout terms. Accepted via checkbox at registration.
- Post-delivery disputes (e.g. a redeemed voucher code) in v1: support ticket
  → admin reviews evidence → manual deposit refund with reason.

## 13. Observability

Per ADR-0067 conventions, bounded labels only (merchant id is bounded —
dozens): orders by merchant/status, deposit debits/refunds, margin-floor
rejections, webhook delivery outcomes.

## 14. Rollout

| Phase | Delivers                                                                                                                                 |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| M1    | orders actor migration; merchant/merchant_users/keys schema; deposit ledger; admin credit/freeze/markup + visibility flags; margin floor |
| M2    | machine API: me/catalog/orders/transactions, HMAC auth, idempotency; born-paid lifecycle; email suppression                              |
| M3    | webhook outbox + SSRF hardening + delivery log; validate endpoints                                                                       |
| M4    | cabinet app: landing, registration + confirmation, all sections; docs; B2B offer                                                         |

M1+M2 alone are sellable to a pilot merchant driven through support + admin.
Before launch: the retail-margin sweep and per-category markup defaults
(§8.3), and the cheap debug SKU check (§2).

## 15. Resolved-question log

Every open question from the brainstorm was decided by the owner: domain
(`reseller.yupay.uz`), cabinet login (email+password+confirmation), launch
catalog (all current top-ups/vouchers, with two-way visibility flags), gifts
(out of v1), test mode (none), markup model (per-SKU 7% default, uniform,
dormant per-merchant adjustment), notifications (none from us; `/me` polling),
naming (`merchant` over `b2b`). None remain open.
