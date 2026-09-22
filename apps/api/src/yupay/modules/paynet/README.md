# `paynet` — Paynet UWS

Paynet is Uzbekistan's terminal and mobile-app payment network. The integration
has two halves that arrive from opposite directions, and confusing them is the
fastest way to misread this module:

- **Out** — `payments/gateways/paynet.py` builds a **deep link** that opens the
  Paynet app with our order id and amount already filled in. The payer confirms
  and types nothing. No API call is made at intent time; the URL is assembled
  client-side, exactly like Payme's checkout link.
- **In** — the money lands later on **`POST /api/v1/payments/paynet/uws`**,
  where we are Paynet's JSON-RPC **server**. Their network calls
  `GetInformation` → `PerformTransaction`, and `CancelTransaction` for a
  reversal.

See [ADR-0078](../../../../../../docs/decisions/0078-paynet-acquirer.md) for why
it is shaped this way, and `docs/runbooks/paynet-troubleshooting.md` for
operating it.

## Endpoint + auth

```
POST /api/v1/payments/paynet/uws
GET  /api/v1/payments/paynet/uws   -- answers -32300 in the body, not a 405
```

- **Transport:** JSON-RPC 2.0. `{"jsonrpc","method","params","id"}` in,
  `{"jsonrpc","result"|"error","id"}` out, with `id` echoed verbatim.
- **Auth:** `Authorization: Basic base64("<paynet_username>:<paynet_password>")`.

**Bad credentials are HTTP 401 with no body.** This is the one place the module
is not a copy of `payme`, and the specs are explicitly opposite: Payme demands
200-with-an-error-object, Paynet demands _"HTTP 401 Unauthorized (а не 200 OK с
JSON-RPC ошибкой)"_. Everything past the auth check is a 200.

**`GetInformation`'s `status` is the string `"0"`, and its `amount` is soʻm, not
tiyin.** Both were flagged in Paynet's own certification pass (2026-09-22):
`status` because every other business value in the envelope is already a
string for the reason the code comments give (a JSON number has been through a
float somewhere on the way), and `amount` because that field is read by a
human on a terminal screen before they confirm — `"13000000"` for a 130 000
soʻm order is not that. `PerformTransaction`'s own `amount` **param** stays
tiyin; the spec fixes that one and does not fix `GetInformation`'s.

## The five methods

| Method               | What it does                                    |
| -------------------- | ----------------------------------------------- |
| `GetInformation`     | Is this order payable, and for exactly how much |
| `PerformTransaction` | Takes the money and settles the order           |
| `CheckTransaction`   | Reports a transaction's state                   |
| `CancelTransaction`  | Reverses a settled payment                      |
| `GetStatement`       | Successful transactions in a window             |

`ChangePassword` is optional in the spec and not implemented — the password is
an env var rotated by an operator, and an endpoint that lets a counterparty
rewrite our own credential store is a liability we have no use for.

### Three places this differs from every other acquirer

**There is no `CreateTransaction`.** `PerformTransaction` opens and settles in
one call, so a `paynet_transactions` row exists only once money has moved.
Idempotency rests entirely on Paynet's `transactionId`, and the unique index on
it is what stops two racing retries charging twice.

**`providerTrnId` must be a 64-bit integer.** Our order ids are UUIDs, so the
number comes from its own sequence (`paynet_provider_trn_id_seq`, starting at
1000 because a one-digit id in a support chat is indistinguishable from a
typo). Allocated once at perform time and never reused — Paynet quotes it in
reconciliation and on receipts.

**`CheckTransaction` on an unknown id is a success, not an error.** The spec
wants a 200 carrying `transactionState: 3`. Answering `203` there turns a
routine "do you know this one?" into an incident.

Its inbound `timestamp` also arrives as `Mon Jun 16 06:12:41 UZT 2021` — a
different format from every other method, frozen for historical reasons. We
require the field and never read it, so the format never has to be parsed.

## Times and amounts

- Every timestamp we emit is `YYYY-MM-dd HH:mm:ss` at **GMT+5**, as a fixed
  offset rather than `ZoneInfo("Asia/Tashkent")`: the contract says +5, and a
  tzdata update that gave Uzbekistan a DST rule must not silently move our
  reconciliation stamps away from what Paynet expects.
- Amounts are **tiyin** everywhere except `GetInformation`'s `fields.amount`,
  which is **soʻm** (1 soʻm = 100 tiyin) — see above. `PerformTransaction`'s
  `amount` param must match `order.total_charged * 100` exactly; anything else
  is `413`, never rounded.

## The error map

Paynet's catalogue was written for utility billing, where an account either
exists or does not. An order has more states, so three of these are a decision
rather than a translation:

| Code  | When                                                                                                                                       |
| ----- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `302` | No order carries that id (also: a malformed id); **also `GetInformation` on an order already paid** — see below                            |
| `201` | `PerformTransaction`: a _new_ `transactionId` targets an order already paid by a different one, **or** the same `transactionId` sent twice |
| `501` | The order exists but is expired, cancelled, held                                                                                           |
| `413` | Amount ≠ the order's charge, to the tiyin                                                                                                  |
| `203` | `CancelTransaction` on an unknown transaction                                                                                              |
| `306` | Cancel refused — goods already delivered                                                                                                   |
| `305` | `serviceId` is not the one we are contracted for                                                                                           |
| `414` | `GetStatement` window is not in the format                                                                                                 |

`201` and `501` are split deliberately: they need different answers from
support — "you already paid" versus "place the order again".

**`GetInformation` on an already-paid order answers `302`, not `201`**
(2026-09-22, Paynet certification feedback) — the one place this module's own
error map is method-aware rather than a flat order-status → code lookup. A
settled bill has nothing left to show a payer, so a status check reads it the
same as "no such order"; `PerformTransaction` keeps `201` for the identical
order, because a client actively trying to pay a second time is owed the
specific reason it is refused. `_load_payable_order`'s `paid_is_not_found`
flag is what the two methods disagree on — see `service.py`.

**A replayed `PerformTransaction` (same `transactionId`) also answers `201`**,
not a silent second success (2026-09-22, same feedback: Paynet's own
certification checklist sends this call twice on purpose and checks for the
error). Nothing re-validates or charges twice either way — the stored row is
untouched — only the response shape changed. `order_already_paid()` and
`transaction_already_exists()` share the numeric code and differ only in the
message, because a support agent reading either off a receipt needs to know
which one actually happened.

The same answer holds when the duplicate arrives _concurrently_ rather than
sequentially: two calls can both pass the lookup before either flushes, and
the unique index rejects the loser. That `IntegrityError` is matched by
constraint name and converted to the same `201` — before this it fell through
to the generic handler and answered `-32603`, a protocol error for what is,
on a retry-happy network, an ordinary event. The match is by name on purpose:
the same flush also writes a `payments` row, and answering "already done" to
_any_ integrity failure would claim a transaction we never wrote.

**`202` ("транзакция уже отменена") is deliberately unused.** Paynet retries a
cancel it never got an answer to, so a second `CancelTransaction` for the same
id is far likelier to be a retry than a second intent — and an error on a retry
reads as a reversal that failed. We echo the stored state 2 instead, which is
both true and idempotent.

## Money safety

- Settlement goes through `payments.service.settle_provider_payment` and a
  reversal through `reverse_provider_payment` — the same chokepoints every
  gateway uses. A Paynet callback never becomes a second path that flips an
  order status or posts to the ledger.
- A cancel is **refused with `306`** once any single `FulfillmentTask` for the
  order has succeeded. A multi-item order can rest at `fulfilling` with one code
  already handed over, which the coarse order-status check misses; clawing the
  money back would hand the customer the goods for free. Such a case is settled
  by a human.
- `refund()` on the gateway always raises: a Paynet reversal is initiated on
  their side and reconciles through `CancelTransaction`.

## Config

| Setting                   | Notes                                                          |
| ------------------------- | -------------------------------------------------------------- |
| `paynet_username`         | Basic-auth user we issued to Paynet                            |
| `paynet_password`         | Its password. In the log redactor — never printed              |
| `paynet_service_id`       | Contractual, from Table 3 of the annex. A foreign one is `305` |
| `paynet_pay_url_template` | The deep link, as a **format string** — see below              |

Either credential empty → the gateway reports `available=False` (the method
disappears from checkout) and the endpoint answers 401 to everything.

**The link template is configuration on purpose.** Paynet supplies the exact
host and parameter names after integration, and the published third-party notes
disagree about all of them, including whether the amount rides in soʻm or
tiyin. Placeholders: `{service_id}`, `{account}` (our order id), `{amount}`
(tiyin) and `{amount_major}` (soʻm) — the template picks the unit. Correcting
the format is an env edit and a restart, not a release.

## Files

```
apps/api/src/yupay/modules/paynet/
  models.py    -- PaynetTransaction + the provider-id sequence (migration 0080)
  errors.py    -- the catalogue above (pure, no I/O)
  service.py   -- the five method handlers
  routes.py    -- POST /payments/paynet/uws, Basic auth, JSON-RPC dispatch
  api.py       -- public surface (router + PaynetTransaction)
```

Plus `payments/gateways/paynet.py` — the `PaymentGateway` adapter, registered as
`"paynet"` in `payments/gateways/__init__.py:REGISTRY`.

## Testing

`apps/api/tests/integration/test_paynet_uws.py` posts JSON-RPC at the endpoint
and covers every method, every error code, both idempotency paths and the two
rules easiest to get wrong by copying Payme (401 on bad auth, state 3 on an
unknown transaction). `apps/api/tests/unit/test_paynet_gateway.py` covers the
deep link, including that the unit stays switchable by env.
`payments` is a ≥95% coverage tier (AGENTS.md §8); this module is in it.
