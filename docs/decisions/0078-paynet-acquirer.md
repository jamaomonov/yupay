# 0078. Paynet as an acquirer: UWS callback plus an app deep link

- **Status**: Accepted
- **Date**: 2026-09-15
- **Deciders**: @jamaomonov
- **Tags**: payments | backend

## Context and problem statement

Paynet is Uzbekistan's terminal and mobile-app payment network — 20M users, and
a brand a buyer in Tashkent recognises without explanation. Adding it puts one
more card route beside Click, Payme and Uzum.

The documentation they sent is **UWS v3.4** (universal connector): a JSON-RPC
2.0 API over HTTP Basic that **we host**, with `GetInformation`,
`PerformTransaction`, `CheckTransaction`, `CancelTransaction` and
`GetStatement`. In that model the payer starts in the Paynet app, finds our
service, types an account identifier, and Paynet calls us. There is no redirect
from our checkout, and that is the opposite of how a storefront sells: our
buyer is already on our page with a formed order, and asking them to switch
apps and retype an order number would lose most of them.

We put that to Paynet directly. Their answer: after the UWS integration they
supply a **link we stitch `order_id` and `amount` into**, which opens the app
with the payment pre-filled — _"клиент ничего не вводит и оплачивает"_.

So the integration is genuinely two-sided, and neither half works alone.

## Decision drivers

- Checkout must stay one click, like the other three acquirers.
- Settlement must reuse the single `payments.service` chokepoint — no acquirer
  gets its own path to flipping an order status or posting to the ledger.
- **The link format is not yet known.** Paynet gives it after integration, and
  the published third-party notes disagree on the host, the parameter names and
  whether the amount is in soʻm or tiyin.
- SLA: 500 ms per transaction, connection cut at 30 s. Nothing on the inbound
  path may call an upstream.

## Considered options

1. **UWS only** — the payer starts in the Paynet app and types an identifier.
2. **UWS + deep link** — we build the link, Paynet settles through UWS.
3. **Wait for a hosted-checkout product** — Paynet has none for this market;
   the only public integration path is UWS.

## Decision outcome

**Chosen option: 2.** `payments/gateways/paynet.py` builds the link;
`modules/paynet/` answers the callback. From a buyer's side it behaves like
Payme: press the button, confirm, come back paid.

Four decisions inside it are worth recording, because each has a cheaper wrong
answer:

**The link template is a config format string, not code.** `{service_id}`,
`{account}`, `{amount}` (tiyin) and `{amount_major}` (soʻm) — the operator's
template picks the unit. We are integrating against a format nobody has given
us yet; making the correction an env edit instead of a release is the
difference between a restart and a deploy on the day they tell us.

**Bad credentials answer HTTP 401, not a 200 with an error body.** This is the
single place the module deliberately diverges from `payme`, whose spec demands
exactly the opposite. Paynet's says it in as many words. Copying Payme here
would have been the easy mistake, so it has a test.

**`providerTrnId` gets its own sequence.** Paynet types it as int64 and our
order ids are UUIDs. It is allocated once at perform time and never reused,
because Paynet quotes it in reconciliation and on receipts.

**`CheckTransaction` on an unknown id is a success carrying `transactionState:
3`**, not error `203`. The spec is explicit, and the difference is whether a
routine reconciliation query reads as an incident.

### Positive consequences

- One more recognised payment method, with no change to checkout's shape.
- Settlement and reversal ride the existing chokepoints, so the ledger and the
  order FSM keep one source of truth.
- Empty credentials make the method vanish from checkout _and_ make the
  endpoint answer 401 — a half-configured deployment cannot take money it
  cannot settle.

### Negative consequences

- A second inbound JSON-RPC surface to keep alive, with a hard SLA.
- The link format ships unverified. It is behind config and covered by a test
  that the unit stays switchable, but the first real payment is the proof.
- No merchant-initiated refund: a reversal starts on Paynet's side and arrives
  as `CancelTransaction`, same as Payme. The admin refund button will refuse.
- `ChangePassword` is unimplemented. The password is an operator-rotated env
  var; an endpoint letting a counterparty rewrite our credential store buys
  nothing.

## Validation

- `apps/api/tests/integration/test_paynet_uws.py` — every method, every error
  code, idempotent replay of perform and cancel, the 401 rule, the state-3
  rule, and that a cancel is refused once goods shipped.
- `apps/api/tests/unit/test_paynet_gateway.py` — the deep link, including that
  an operator can switch the amount unit by env and that an unknown placeholder
  fails with a sentence rather than a `KeyError`.
- The real proof is the first sandbox payment against the format Paynet
  supplies; until then the template default is a guess and is marked as one.

## References

- [ADR-0034](./0034-payme-merchant-api.md) — the same "we are their JSON-RPC
  server" shape, and the module this one is modelled on.
- UWS v3.4 spec + «Порядок технического взаимодействия» v1.5 (contract annex).
- `apps/api/src/yupay/modules/paynet/README.md`
- `docs/runbooks/paynet-troubleshooting.md`
