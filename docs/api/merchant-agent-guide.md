# YuPay Merchant API — a guide for your AI coding agent

**Give this file to the AI agent that is writing your integration.** It is written to
be pasted into a system prompt or dropped into a repository as context. It describes
the YuPay Merchant API v1 as it actually behaves, so the agent does not have to guess.

> **This file goes stale.** It reflects the contract on **2026-09-20**. If anything
> here disagrees with <https://reseller.yupay.uz/docs>, the site is right and this file
> is old. Check the site before concluding that the API is broken.

---

## What you are integrating

YuPay Merchant API v1 is a **signed, server-to-server wholesale ordering API**. You
buy digital top-ups and vouchers at wholesale and resell them. Orders are settled
instantly from a **prepaid USD deposit** — there is no invoicing and no card flow in
the API.

Base URL: `https://api.yupay.uz`

---

## Rules for the agent

1. **Never put the secret in a prompt, a chat message, a screenshot, or a git
   repository.** It belongs in server-side configuration or a secret manager. If it
   has ever appeared in any of those places, treat it as compromised and issue a new
   key.
2. **Do not invent endpoints, fields, error codes or statuses.** There are six
   endpoints and they are all listed below. If something you need is missing, it does
   not exist in v1 — ask YuPay rather than working around it.
3. **Do not disable signature verification to "get it working".** The signature is the
   only authentication there is, in both directions.
4. **Parse leniently.** New fields are added to responses without warning; unknown
   fields must be ignored, not rejected. A breaking change would ship as
   `/merchant/v2`.

---

## 1. Your three credentials

Three values, three prefixes, deliberately distinct so a mixed-up config fails loudly
instead of producing a signature nobody can explain:

| Prefix  | What it is               | Secret? | Where it goes                                       |
| ------- | ------------------------ | ------- | --------------------------------------------------- |
| `ypm_`  | Key id — the public half | No      | `X-Merchant-Key` header on every request            |
| `ypms_` | **Your secret key**      | **Yes** | Never transmitted — it is the HMAC key for signing  |
| `ypmw_` | Webhook signing secret   | Yes     | Never transmitted — used to verify what YuPay sends |

`ypm_` and `ypms_` are two halves of **one credential**, issued together in one
response. `ypmw_` is a separate thing that protects the opposite direction and has
nothing to do with signing your requests.

**`ypms_` is displayed exactly once**, at the moment the key is created. Nothing can
show it again — YuPay stores it encrypted and decrypts it only inside signature
verification. If it is lost, the only path forward is a new key.

Rotation causes no downtime: several keys can be live at once. Create the new key,
deploy it, then revoke the old one.

A correct configuration looks like this — note that all three values differ, and the
webhook secret is present **only if you have configured a webhook**:

```
YUPAY_API_BASE        = "https://api.yupay.uz"
YUPAY_MERCHANT_KEY    = "ypm_..."     # goes in the X-Merchant-Key header
YUPAY_MERCHANT_SECRET = "ypms_..."    # HMAC key, never sent
YUPAY_WEBHOOK_SECRET  = "ypmw_..."    # only if webhooks are set up
```

---

## 2. Signing a request

Three headers on every call:

```
X-Merchant-Key:       ypm_...
X-Merchant-Timestamp: 1758375600
X-Merchant-Signature: <lowercase hex HMAC-SHA256>
```

`X-Merchant-Timestamp` is Unix seconds and must be within **±300 s** of YuPay's clock.
Outside that window you get `401 stale_timestamp` — fix the server clock (NTP), the
window will not be widened.

The signature is HMAC-SHA256, keyed by your `ypms_` secret, over exactly five fields
joined by a single LF (`\n`, 0x0A — never CRLF):

```
{timestamp}\n{METHOD}\n{raw_path}\n{raw_query}\n{sha256_hex(body)}
```

- `timestamp` — the same value you put in the header.
- `METHOD` — upper case: `GET`, `POST`.
- `raw_path` — the path **exactly as it appears on the request line**, still
  percent-encoded. Do not URL-decode it first.
- `raw_query` — everything after `?`, without the `?`, exactly as sent. Empty string
  when there is no query. **The query string is signed**, so `?limit=50` must be
  included.
- `sha256_hex(body)` — the hex SHA-256 of the **exact request-body bytes you send**.
  For a request with no body this is the digest of the empty string:
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

A signature is **not** single-use. Retrying an identical request after a timeout is
safe and expected.

### Reference implementation

```python
import hashlib, hmac, json, os, time
import requests

API   = "https://api.yupay.uz"
KEY   = os.environ["YUPAY_MERCHANT_KEY"]      # ypm_...
SECRET = os.environ["YUPAY_MERCHANT_SECRET"]  # ypms_...

def call(method: str, path: str, query: str = "", body: dict | None = None):
    raw = b"" if body is None else json.dumps(body, separators=(",", ":")).encode()
    ts = str(int(time.time()))
    canonical = "\n".join([ts, method.upper(), path, query, hashlib.sha256(raw).hexdigest()])
    sig = hmac.new(SECRET.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    url = API + path + (("?" + query) if query else "")
    return requests.request(
        method, url, data=raw,
        headers={
            "X-Merchant-Key": KEY,
            "X-Merchant-Timestamp": ts,
            "X-Merchant-Signature": sig,
            "Content-Type": "application/json",
        },
        timeout=30,
    )
```

The critical detail: `raw` is computed **once** and both hashed and sent. Serialising
the body twice — once for the digest, once for the request — lets a JSON library
reorder keys or change spacing between the two, and the signature will not verify.

### When a signature will not verify

Check in this order; it is almost always one of the first three.

1. Signing the **encoded** path, or a decoded one?
2. Is the query string included?
3. Is the digest taken over the **exact bytes sent**, or over a re-serialised object?
4. `\n` (LF) or `\r\n` (CRLF)?
5. Using `ypms_`, not `ypmw_`?
6. Server clock drift.

There is no "Try it out" button in the API reference, by design: it would ask you to
paste your secret into a web page. Ready-made cURL, Python and Node samples with the
signature already computed are at <https://reseller.yupay.uz/docs>.

---

## 3. The endpoints — there are six

| Method | Path                                      | Purpose                                               |
| ------ | ----------------------------------------- | ----------------------------------------------------- |
| GET    | `/merchant/v1/catalog`                    | Your wholesale price list, priced for your account    |
| GET    | `/merchant/v1/me`                         | Your profile and live deposit balance                 |
| POST   | `/merchant/v1/orders`                     | Place an order, settled from the deposit              |
| GET    | `/merchant/v1/orders/{merchant_order_id}` | Read one of your orders back, with its delivered code |
| GET    | `/merchant/v1/transactions`               | Your deposit ledger, newest first                     |
| POST   | `/merchant/v1/validate/player`            | Check an end customer's player id before ordering     |

Each can answer `401`, `403`, `422` or `429` in addition to its success code.

Conventions everywhere:

- **Money is a decimal string**, never a number: `"16.54"`. Parse it with a decimal
  type. Floating point here becomes a rounding complaint later.
- **Timestamps are ISO 8601 UTC.**

### Placing an order

`POST /merchant/v1/orders` is idempotent on **your own `merchant_order_id`** — there is
no `Idempotency-Key` header on this endpoint.

- Same id, same body → returns the order already placed. Safe to retry.
- Same id, **different** body → `409 order_id_reused`.

**Generate the id once, before the first attempt, and reuse it for every retry of that
same purchase.** Generating a fresh id on retry is how you buy the same thing twice.

Refusals you should handle explicitly: `insufficient_deposit`, `item_unavailable`,
`price_changed` (your quoted price drifted more than ±2% from YuPay's),
`amount_out_of_range`, `quantity_out_of_range`, `margin_floor`.

### Reading an order back

Status runs `paid` → `fulfilling` → `delivered`, or `failed`.

`failed` arrives two ways, and `failure_reason` distinguishes them: YuPay support
closing an undeliverable order, and a delivery failure whose **entire** charge is
already back on your deposit.

**Treat any status you do not recognise as still in flight.** New values may be added.

---

## 4. Your deposit

The balance is prepaid USD. `GET /merchant/v1/transactions` returns the movements with
a **signed** `amount_usd` that sums to the balance `GET /merchant/v1/me` reports:

| `kind`                    | Meaning                                   | Sign |
| ------------------------- | ----------------------------------------- | ---- |
| `merchant_deposit_credit` | YuPay credited you (top-up or settlement) | `+`  |
| `merchant_order_charge`   | An order spent it                         | `−`  |
| `merchant_order_refund`   | A failed delivery returned the charge     | `+`  |
| `merchant_deposit_debit`  | YuPay took a correction back off          | `−`  |

Display a `kind` you do not recognise rather than dropping it — the vocabulary is open.

When a delivery fails and the upstream supplier returned the money, your deposit is
refunded **automatically** and the order closes as `failed`. When the money was spent,
or the outcome cannot be determined, it is not refunded automatically — that is a
decision a person at YuPay makes, so contact them.

---

## 5. Checking a player id

`POST /merchant/v1/validate/player` checks an end customer's player id before you
order for them. Two honest limits:

- It is **advisory**. A positive answer is not a guarantee the order will deliver.
- Not every brand supports it. Where there is no upstream validator, the endpoint will
  not claim a verification it did not perform.

It is the right thing to call from your checkout form, and the wrong thing to treat as
a delivery guarantee.

---

## 6. Webhooks

YuPay POSTs to a URL you configure in the cabinet. **Three event types, and only
three:**

| Event                  | Body                                               |
| ---------------------- | -------------------------------------------------- |
| `order.status_changed` | `merchant_order_id`, `order_id`, `status`, `at`    |
| `balance.credited`     | `amount_usd`, `balance_usd` — decimal **strings**  |
| `webhook.test`         | Sent when you press the test button in the cabinet |

Headers on every delivery:

```
X-Yupay-Delivery:  <delivery id — stable across retries of the same event>
X-Yupay-Event:     order.status_changed | balance.credited | webhook.test
X-Yupay-Timestamp: <unix seconds>
X-Yupay-Signature: <lowercase hex HMAC-SHA256>
```

Verify with your **`ypmw_`** secret over four LF-separated fields:

```
{timestamp}\n{delivery_id}\n{event_type}\n{sha256_hex(body)}
```

Receiver requirements:

- **Verify the signature before parsing the body.**
- **Delivery is at-least-once.** The same event can arrive more than once —
  deduplicate on `X-Yupay-Delivery`.
- **Answer `2xx` quickly.** `408`, `429` and `5xx` are retried with backoff. Any other
  `4xx`, and any redirect (redirects are never followed), count as a failure. A long
  run of failures disables the endpoint and you will have to re-enable it in the
  cabinet.
- **A balance going down sends nothing.** There is no `balance.debited` event. A
  correction appears on `/merchant/v1/transactions`, not in your receiver — so do not
  treat webhooks as a complete ledger feed.

---

## 7. Errors

RFC 7807 problem documents:

```json
{
  "type": "https://app.yupay.uz/errors/validation",
  "title": "Validation failed",
  "status": 422,
  "detail": "human-readable explanation",
  "extra": { "...": "context" }
}
```

**Branch on `code`, never on `detail`.** The prose can change; the code is the
contract. The published vocabulary:

**Auth and access** — `missing_credentials`, `invalid_credentials`, `stale_timestamp`,
`ip_not_allowed`, `merchant_frozen`

**Ordering** — `order_id_reused`, `item_unavailable`, `price_changed`, `margin_floor`,
`insufficient_deposit`, `amount_required`, `amount_not_accepted`,
`amount_out_of_range`, `quantity_required`, `quantity_not_accepted`,
`quantity_out_of_range`

**Reading and settlement** — `order_not_found`, `unknown_status`, `invalid_cursor`,
`bad_window`, `deposit_already_returned`, `order_already_settled`,
`order_still_fulfilling`

Two worth understanding rather than just catching:

- **`merchant_frozen` (403)** — the account is under review. It blocks **orders only**;
  reads still work and the deposit can still be credited.
- **`ip_not_allowed` (403)** — that key carries an IP allowlist and the request did not
  come from a listed address. Usually a new server or an added NAT address; ask YuPay
  to update the list.

---

## 8. What you can do yourself, in the cabinet

<https://reseller.yupay.uz> — email and password, with confirmation and password reset.

- **API keys** — create one (the `ypms_` secret is shown once, right then; save it
  immediately), list them including revoked ones, revoke one.
- **Webhook** — set the URL, rotate the `ypmw_` secret, send a test event, disable it.
  Delivery health is shown here, which is where to look when events stop arriving.
- **Orders** — browse yours, export CSV.
- **Deposit statement** — the ledger, with CSV export.
- **Catalogue** — the wholesale price list, with CSV export.

Documentation, in Russian, English and Uzbek, at
<https://reseller.yupay.uz/docs>:

`quickstart` · `authentication` · `api` · `errors` · `webhooks` · `schemas`

Machine-readable OpenAPI for the Merchant API is linked from the `api` page — prefer
it over this file when generating client code.

---

## 9. When to stop and ask a human

Some things only YuPay can do. If you are blocked on one of these, stop guessing and
write to [@jama_omonov](https://t.me/jama_omonov) on Telegram:

- issuing or revoking a key for you, if you cannot reach the cabinet;
- funding the deposit;
- un-freezing an account (`merchant_frozen`);
- updating a key's IP allowlist;
- refunding an order whose money was spent or whose outcome is unclear;
- anything where this file and <https://reseller.yupay.uz/docs> disagree.
