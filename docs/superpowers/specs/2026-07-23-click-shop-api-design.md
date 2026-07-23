# Click (Shop API) Integration — Design Spec

> Status: draft for review. Third acquirer after [Payme] and [Uzum]
> (`2026-07-22-{payme,uzum}-merchant-api-design.md`). Click's Shop API is the
> same _inverted_ webhook model, so this spec mirrors those and calls out only
> where Click differs (MD5-signed **form-encoded** requests, **two** endpoints,
> **two** services, amounts in **soums**).

**Source of truth:** Click official docs (`https://docs.click.uz/en/shop-api/*`,
captured 2026-07-23) + the official `click-llc/click-integration-php` library.
All request/response fields, the `sign_string` formulas, and error codes below
are quoted from there.

---

## 1. Goal

Let a customer pay for a YuPay order with **Click** (Uzbekistan), on **both**
surfaces: the web storefront (`yupay.uz`) and the Telegram mini app
(`yupayapp_bot`). Click is a new acquirer alongside Octo, Payme, and Uzum.

Click gave us **two services** sharing one merchant (`merchant_id = 63276`):

| Surface        | service_id | merchant_user_id | secret                 |
| -------------- | ---------- | ---------------- | ---------------------- |
| web (yupay.uz) | 108149     | 88645            | `CLICK_SECRET_KEY_WEB` |
| bot (mini app) | 108150     | 88644            | `CLICK_SECRET_KEY_BOT` |

Config for all of this already landed (commit `1efe80e`): `Settings.click_*`
fields + the `infra/secrets-example/api.env` block + log redaction.

---

## 2. The key architectural fact (Click, like Payme/Uzum, is inverted)

Octo is a classic gateway (we call it). Click's **Shop API** inverts that: Click
drives the payment by calling **two webhooks on our server** as the customer
pays in Click Up / on `my.click.uz`:

- `POST /prepare` (`action = 0`) — validate the order; we return our
  `merchant_prepare_id`.
- `POST /complete` (`action = 1`) — Click debited the customer; we deliver the
  goods and return our `merchant_confirm_id`.

We **own the transaction state machine** and its idempotency. Each webhook is a
**form-urlencoded** POST authenticated by an **MD5 `sign_string`** keyed on the
per-service `SECRET_KEY`. We reuse the exact same `payments` provider-lifecycle
chokepoints Payme/Uzum use, so a third acquirer never becomes a second code path
that flips order status or posts the ledger.

---

## 3. Decisions locked during brainstorming

1. **Shop API (Prepare/Complete) + the pay link, both surfaces.** Web shows both
   Click buttons (CLICK + pay-by-card — variants of the same `my.click.uz` page);
   the mini app opens the pay link via `openExternalLink` (already shipped). The
   Merchant API (invoice/card-token) and Telegram Bot Payments API are **out of
   scope** (§15).
2. **`merchant_trans_id` = our `order_id`.** Click echoes it on both webhooks.
3. **Two services routed by surface (recommended: two provider ids).** See §4/§9
   and the open decision in §16 #1.
4. **Amount is soums (major units), compared as `Decimal`.** `amount` is a float
   in soums; we compare it to `order.total_charged` (already whole-so'm rounded
   at checkout by `orders.service._round_to_payable`) via `Decimal`, never float
   equality. Mismatch → `-2`.
5. **Refund is out of scope (v1).** Reversal is Click-initiated (their Merchant
   API `/cancel` or cabinet). We only handle Click's "negative `error` in the
   request → cancel our side and return `-9`" rule (§7).
6. **Signature over the RAW request values.** The MD5 is built from the raw,
   as-received string field values (not re-serialized `Decimal`s), because
   Click's own signature used the exact wire strings. See §6.

---

## 4. Architecture overview

New module `apps/api/src/yupay/modules/click/`, structured like `uzum/`:

```
modules/click/
├── api.py        # public interface (re-exports router + service)
├── models.py     # ClickTransaction (migration 0029)
├── errors.py     # ClickError(code) + to_response() + factories (0/-1..-9)
├── signature.py  # sign_string build + verify (MD5, per-service secret)
├── service.py    # prepare / complete handlers + build_checkout_url
├── routes.py     # POST /prepare, POST /complete (form-encoded, always 200 JSON)
├── README.md
```

Mounted under `api/v1/__init__.py` at `/api/v1/payments/click/*`. Reuses the
payments lifecycle hooks:

- `settle_provider_payment` — on `/complete` (order → paid, fulfilment starts).
- `cancel_pending_provider_payment` — on a negative-`error` request (Click abort)
  and on the timeout sweep of an un-completed prepare.

`ClickGateway` (in `payments/gateways/click.py`) implements `create_intent` —
builds the `my.click.uz/services/pay` URL for the surface's service. `refund`
raises (reversal is Click-side); `verify_webhook` raises `PaymentNotIntegratedError`.

**Two-service routing (recommended):** register **two** gateway providers —
`"click"` (web, service 108149 / `CLICK_SECRET_KEY_WEB`) and `"click_miniapp"`
(bot, service 108150 / `CLICK_SECRET_KEY_BOT`). Each frontend selects its own
provider id at checkout (web → `click`, mini app → `click_miniapp`). On the
inbound Prepare/Complete side, the incoming `service_id` deterministically picks
which secret verifies the signature — independent of the provider id. (Alternative
in §16 #1.)

---

## 5. Data model

`ClickTransaction` (Alembic migration `0029`):

| Column                                       | Type                       | Notes                                                                 |
| -------------------------------------------- | -------------------------- | --------------------------------------------------------------------- |
| `id`                                         | str PK                     | our id (`new_id()`)                                                   |
| `merchant_prepare_id`                        | bigint IDENTITY            | the **integer** id we return to Click at Prepare (Click requires int) |
| `click_trans_id`                             | bigint                     | Click's payment id (`click_trans_id`)                                 |
| `service_id`                                 | bigint                     | which Click service (108149/108150)                                   |
| `order_id`                                   | str FK→orders              | from `merchant_trans_id`                                              |
| `payment_id`                                 | str FK→payments (SET NULL) | the backing `payments` row                                            |
| `amount`                                     | Numeric(20,6)              | soums, as received (for audit + the Complete cross-check)             |
| `status`                                     | str CHECK                  | `PREPARED` / `CONFIRMED` / `CANCELLED`                                |
| `click_paydoc_id`                            | bigint null                | Click's `click_paydoc_id`                                             |
| `prepare_time`/`complete_time`/`cancel_time` | timestamptz null           | set on each transition                                                |
| `created_at`/`updated_at`                    | timestamptz                | standard                                                              |

`merchant_prepare_id` is a DB IDENTITY/sequence bigint (Click's field is `int`;
our other ids are UUID strings, which Click won't accept here). Unique index on
`(click_trans_id, service_id)`; index on `order_id`; the sequence backs
`merchant_prepare_id`.

---

## 6. Transport + auth (signature)

- **Transport:** Click sends **`application/x-www-form-urlencoded` POST** (not
  JSON — unlike Payme/Uzum). We read form fields. Response is **JSON**.
- **We always return HTTP 200** with a JSON body carrying `error`/`error_note`
  (+ the echo fields) — a signature/validation failure is a body-level negative
  `error`, never an HTTP 4xx/5xx.
- **Signature:** every request carries `sign_time` + `sign_string`. We:
  1. Pick the secret by the request's `service_id` (108149 → web secret,
     108150 → bot secret); unknown service → `-1` (treat as sign failure /
     unauthorised).
  2. Build the MD5 over the **raw string field values** in the documented order:
     - Prepare: `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + amount + action + sign_time)`
     - Complete: `md5(click_trans_id + service_id + SECRET_KEY + merchant_trans_id + merchant_prepare_id + amount + action + sign_time)`
  3. Constant-time compare to the received `sign_string`; mismatch → `-1`
     (`SIGN CHECK FAILED!`). **The `amount` used in the hash is the raw wire
     string** (Click formats it, e.g. `1000.00`); do not reformat it.
- No IP allowlist at the app layer initially (the signature is the gate); a
  Caddy allowlist can be added later once Click's source IPs are confirmed (§16).

---

## 7. The two webhooks (exact contract)

Common request fields: `click_trans_id` (bigint), `service_id` (int),
`click_paydoc_id` (bigint), `merchant_trans_id` (our order_id), `amount` (float,
soums), `action`, `error` (int, 0 = ok), `error_note`, `sign_time`
(`YYYY-MM-DD HH:mm:ss`), `sign_string`.

### `POST /prepare` (`action = 0`) — validate

**Response:** `{ "click_trans_id", "merchant_trans_id", "merchant_prepare_id", "error": 0, "error_note": "Success" }`

**Logic:**

1. Verify signature (§6) → else `-1`.
2. `action != 0` → `-3` (action not found).
3. If the request's own `error < 0` (Click aborted) → cancel our side, return
   `-9` (see the cancel rule below).
4. Resolve order by `merchant_trans_id`; missing → `-5` (user/order not found).
   Order already paid → `-4` (already paid). Order cancelled/expired → `-9`.
5. `Decimal(amount) != order.total_charged` → `-2` (incorrect amount).
6. Insert a `ClickTransaction` (status `PREPARED`, allocate the bigint
   `merchant_prepare_id`), attach/ensure a pending `payments` row (provider
   `"click"`/`"click_miniapp"`). Idempotent on `(click_trans_id, service_id)` —
   a replay returns the same `merchant_prepare_id`.
7. Return `error: 0` + `merchant_prepare_id`.

### `POST /complete` (`action = 1`) — settle

**Response:** `{ "click_trans_id", "merchant_trans_id", "merchant_confirm_id", "error": 0, "error_note": "Success" }`

**Logic:**

1. Verify signature (§6) → else `-1`.
2. `action != 1` → `-3`.
3. If the request's `error < 0` → cancel our side, return `-9`.
4. Load the `ClickTransaction` by `merchant_prepare_id` (+ matching
   `click_trans_id`/`service_id`); missing → `-6` (transaction not found).
5. If already `CONFIRMED` → `-4` (already paid) _(Click's replay signal)_. If
   `CANCELLED` → `-9`.
6. `Decimal(amount) != txn.amount` → `-2`.
7. `settle_provider_payment` (payment → succeeded, order → paid, fulfilment
   starts); set status `CONFIRMED` + `complete_time`; `merchant_confirm_id` =
   the same numeric id (or a dedicated confirm sequence).
8. Return `error: 0` + `merchant_confirm_id`.

### The negative-`error` cancel rule

Per the docs: **"Upon receiving a negative error code [in the request], the
Merchant must cancel the payment in the billing system and return error code
`-9`."** So on either webhook, if the inbound `error < 0`, we
`cancel_pending_provider_payment` (if the txn is still PREPARED) / leave a
CONFIRMED txn's money intact (guard like Uzum — never cancel a settled payment),
set status `CANCELLED`, and return `-9`.

---

## 8. Error catalogue (`errors.py`)

`ClickError(code: int, note: str)` with `.to_response(**echo)` →
`{"error": code, "error_note": note, **echo}`. Factories (code → note, verbatim
from the docs):

| Code | error_note                    | When                                                     |
| ---- | ----------------------------- | -------------------------------------------------------- |
| `0`  | `Success`                     | operation ok                                             |
| `-1` | `SIGN CHECK FAILED!`          | signature mismatch / unknown service                     |
| `-2` | `Incorrect parameter amount`  | `amount` ≠ order/txn amount                              |
| `-3` | `Action not found`            | `action` not 0/1                                         |
| `-4` | `Already paid`                | Complete on an already-confirmed txn                     |
| `-5` | `User does not exist`         | `merchant_trans_id` (order) not found                    |
| `-6` | `Transaction does not exist`  | `merchant_prepare_id` not found                          |
| `-7` | `Failed to update user`       | internal update failure                                  |
| `-8` | `Error in request from click` | malformed request from Click                             |
| `-9` | `Transaction cancelled`       | cancelled (Click abort / negative inbound error / stale) |

---

## 9. Payment initiation (`create_intent`)

`ClickGateway.create_intent(order, return_url)`:

- Guard `order.currency == "UZS"`, `total_charged > 0`.
- `amount = order.total_charged` (soums; the pay URL takes soums, not tiyin).
- Build: `{click_pay_url}?service_id=<svc>&merchant_id=<merchant_id>&amount=<amount>&transaction_param=<order.id>&return_url=<return_url>`
  where `<svc>` is this provider's service (web 108149 / bot 108150) and
  `transaction_param` is our order id (Click echoes it back as
  `merchant_trans_id`).
- Return `PaymentIntent(external_id=f"click:{order.id}", intent_url=<url>,
status="pending", extra_metadata={"amount_soums": str(amount)})`.

On mobile this deep-links into Click Up / opens `my.click.uz`; the mini app opens
it via `openExternalLink` (shipped). The web storefront renders the two Click
buttons (CLICK + pay-by-card) — both point at `my.click.uz` (§16 #2).

---

## 10. State machine + timeouts

```
/prepare  → PREPARED
/complete → CONFIRMED   (settle: order paid, fulfilment started)
negative error / stale → CANCELLED
```

- **Stale-prepare sweep:** a scheduler job (`click_timeout.py`, mirroring
  `uzum_timeout.py`) fails `PREPARED` transactions with no `/complete` after a
  cutoff (confirm Click's window; default 30–60 min), setting them `CANCELLED`
  and cancel-pending on the still-pending payment. **Same money-safety guard as
  Uzum:** only cancel a payment that is still `pending` (never a shared succeeded
  one) — carry that lesson forward from the Uzum final-review Critical.

---

## 11. Config (already landed — `core/config.py`)

`click_merchant_id`, `click_service_id_web` (108149), `click_service_id_bot`
(108150), `click_secret_key_web`, `click_secret_key_bot`,
`click_merchant_user_id_web` (88645), `click_merchant_user_id_bot` (88644),
`click_pay_url` (`https://my.click.uz/services/pay`). Blank int → None validator;
secrets in `REDACTED_KEYS`. `ClickGateway.available` (per provider) = merchant_id

- that surface's service_id + secret all set.

---

## 12. Error handling / edge cases

- **Idempotency:** Prepare replay (same `click_trans_id`+`service_id`) → same
  `merchant_prepare_id`; Complete replay on a CONFIRMED txn → `-4`. Row-locked
  (`FOR UPDATE`) so concurrent webhooks serialise; a concurrent Prepare INSERT
  race surfaces as an `IntegrityError` on `(click_trans_id, service_id)` — catch
  - re-read (mirror the Uzum §12 savepoint fix).
- **Decimal amount:** compare `Decimal(str(amount))` to `total_charged`; never
  float `==`.
- **Signature over raw strings:** verify against the exact wire values; a
  reformatted amount would break the hash.
- **Money-safety (from the Uzum Critical):** `_ensure_payment` reuse means a
  payment can be shared across transactions — the cancel path (negative error,
  stale sweep) must guard `payment.status == "pending"` before cancel-pending.
- **Commit inside the try/except**, rendering `-7`/`-8` at HTTP 200 if the commit
  itself fails.

---

## 13. Testing

Coverage gate ≥ 95% (payments-adjacent). Integration tests (testcontainers),
mirroring `test_uzum_*`:

- Signature: valid → proceeds; tampered `sign_string` → `-1`; unknown
  `service_id` → `-1`; the web-secret vs bot-secret selection by `service_id`.
- `/prepare`: success (+ `merchant_prepare_id`), `-2` wrong amount, `-4` already
  paid, `-5` unknown order, `-9` cancelled/expired order, replay idempotency,
  concurrent-insert race → same id.
- `/complete`: success + settle (order paid), `-6` unknown prepare id, `-4`
  replay, `-9` on a cancelled txn, `-2` amount mismatch.
- Negative inbound `error` → cancel + `-9`; on a CONFIRMED txn the shared payment
  is NOT clawed back.
- Gateway: `available` per provider, `create_intent` builds the exact pay URL for
  each surface's service, UZS guard.
- Scheduler: stale PREPARED → CANCELLED + cancel-pending (money-safety guard).
- Every response is HTTP 200 with a JSON `error` body; form-encoded parsing.

---

## 14. Docs

ADR `0036-click-shop-api.md`; runbook `click-troubleshooting.md` (error table,
sign-check debugging, the stale-prepare sweep, two-service secret selection);
sequence diagram `click-payment.mmd`; module-map row; module `README.md`;
regenerate `docs/api/openapi.json`.

---

## 15. Out of scope (v1)

- Click **Merchant API** (invoice creation, `/payment/status`, `/cancel`,
  `/card/create` card tokens) — we only implement the **Shop API** callbacks +
  the pay link.
- **Telegram Bot Payments API** (BotFather provider token, in-Telegram card
  entry) — redundant with the pay link, which already works in the mini app.
- Merchant-initiated refunds (Click-side).
- CLICK Pass, fiscalization, Split/Advanced Shop.

---

## 16. Open decisions flagged (not silently assumed)

1. **Two-service routing.** Recommended: two provider ids (`click` web /
   `click_miniapp` bot), each frontend selects its own. Alternative: a single
   `click` provider + a `channel` hint threaded through
   `payments.service.create_intent`. Confirm which — depends on whether the web
   and mini-app checkouts can each set their own provider id (they have separate
   payment-method configs). The inbound Prepare/Complete side is unaffected (it
   routes by `service_id`).
2. **Web's two buttons.** The exact `my.click.uz` URLs / params for the standard
   CLICK button vs "pay by card" (`click-pay-by-card`) — confirm from the button
   docs whether pay-by-card is a URL param (e.g. `card_type`) or a distinct path;
   both still settle through the same Prepare/Complete.
3. **Content type.** Confirm Click sends `application/x-www-form-urlencoded` (the
   PHP lib reads `$_POST`); if any service is configured for JSON, the route must
   accept both.
4. **Stale-prepare window.** Confirm Click's own timeout before we sweep
   PREPARED → CANCELLED.
5. **Amount wire format in the sign string.** Confirm Click's `amount` string
   form (e.g. `1000.00`) so the MD5 matches — verify against a real sandbox
   request; build the hash from the raw value regardless.
6. **Source IPs** for an optional Caddy allowlist (later; signature is the gate).

---

## 17. Build order (feeds the plan)

1. Migration `0029_click_transactions` + `ClickTransaction` (incl. the
   `merchant_prepare_id` sequence).
2. `errors.py` (0/-1..-9 factories + `to_response`).
3. `signature.py` (build + constant-time verify, per-service secret).
4. `service.py` — `prepare` / `complete` + `build_checkout_url` (reuse payments
   hooks + the money-safety cancel guard).
5. `routes.py` — form-encoded POST `/prepare` `/complete`, always-200 JSON,
   sign + service-id guards, commit-inside-guard; mount + OpenAPI.
6. `ClickGateway` (two providers) + REGISTRY + `available`.
7. Scheduler `click_timeout.py` (stale-prepare sweep, money-safety guard).
8. Miniapp + web Click method wiring (provider ids per surface) + i18n.
9. Tests (≥95%).
10. Docs (ADR-0036, runbook, sequence diagram, module map, README).
