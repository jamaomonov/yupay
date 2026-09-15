# 0076 — The merchant cabinet: a browser surface of its own, on an origin of its own

- Status: accepted
- Date: 2026-09-15
- Spec: `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md` (§11)
- Predecessors: ADR-0068 (the M1 foundation), ADR-0069 (the machine API this sits beside)

## Context

M2 and M3 gave a reseller everything their **server** needs: a signed request
line, a priced catalog, an order endpoint, webhooks, refunds. What none of it
gave them is a way to _look_. Onboarding today means a support conversation
that ends with a key pasted into a chat, and every question after it — "what
did I spend yesterday", "did that order deliver", "what is my markup on
Stars", "rotate my key" — is another message to a human.

M4 closes that: a browser surface where a reseller signs up, accepts the
offer, reads the wholesale price list, places a first order without writing
any code, watches their orders and statement, and issues and revokes their own
credentials.

The decisions below are the ones a future maintainer would otherwise
re-litigate. One of them (§2b) **reverses** a call ADR-0070 made four weeks
earlier, and is written up at length for that reason.

## Decisions

### 1. A separate Next.js app on its own origin, not a section of an existing one

`apps/merchant`, served at `reseller.yupay.uz`. Three surfaces were candidates for
absorbing it and all three were refused:

- **`apps/web`** is the storefront: public, SEO-driven, guest-friendly, and
  built around a retail customer buying one top-up. A signed-in wholesale
  cabinet inside it would put two products behind one origin and one bundle.
- **`apps/admin`** is ours. A reseller is not staff, and the blast radius of
  "the panel where our operators adjust ledgers" gaining an external audience
  is not worth the code it would save.
- **`apps/partners`** is the **affiliate programme**, not this. The names are
  adjacent and the audiences are not: an affiliate refers customers and takes
  a payout; a reseller buys inventory against a deposit and integrates a
  machine API. Merging them would mean one login owning two unrelated
  balances.

The origin is the load-bearing half. The cabinet keeps a session token in
`localStorage`, and an origin is the only boundary the browser enforces around
one. A section of `yupay.uz` would put a reseller's token in reach of every
script the storefront ever loads — analytics, a marketing tag, a future embed.

### 2. The browser talks to a BFF (`/merchant/cabinet`), never to `/merchant/v1`

`/merchant/v1` authenticates with an HMAC signature over the request line. That
credential belongs on a reseller's **server**. Shipping it to a browser — even
"just for the cabinet" — would mean the secret exists in a place an XSS can
read it, and would make every future cabinet feature a change to a contract
third parties implement against.

So the cabinet signs in with a password, carries a short-lived
`merchant_access` JWT, and this router does the work on their behalf. Two
consequences worth naming:

- **The DTOs are separate on purpose.** `machine_schemas.py` is a frozen
  third-party contract; `cabinet_schemas.py` serves our own browser and may
  change with the app that reads it. Sharing them would make every cabinet
  tweak a breaking API change. What _is_ shared is the **value types**
  (`UsdAmount`, `UsdBalance`) — a rounding rule copied is a rounding rule that
  drifts, and a machine contract cannot hand a client two shapes for one
  quantity.
- **Ordering walks the machine API's own path.** `quote`, the margin floor,
  the deposit charge, the fulfilment enqueue — with a minted `manual-<uuid>`
  standing in for the `merchant_order_id` a person should not have to invent.
  A cabinet order and an API order are therefore the same kind of thing in
  history, in the ledger and in a dispute, which is what lets the catalog page
  double as the no-code first purchase.

### 2b. Webhook configuration moves to the merchant, because the defences did not

Through M3a, setting a webhook URL was admin-only, and ADR-0070 gives the
reason: a write on `/merchant/v1` "would exist only to let a stranger aim our
worker at an address of their choosing". That reason does not survive M4, and
it is worth saying why rather than quietly reversing it.

The two SSRF defences live **below** the caller, not in the admin router.
`admin.validate_webhook_url` refuses a non-https URL or a host that resolves
into a blocked range at **save** time, and it is the same function the
catalog's image URLs go through rather than a second copy of the ranges;
`core/outbound.py` pins one resolved address per attempt at **send** time, so
a host that answers publicly on the first lookup and privately on the second
does not get a second lookup. Neither asks who called. A merchant therefore
cannot aim our worker anywhere an operator could not, which is the property
that makes the control safe to hand over — not that a cabinet session is
somehow more trusted than an anonymous one.

What the merchant gets besides the four writes is the **delivery log**:
the event, the address it went to, the code that came back, their server's own
body, and our error text. `merchant_webhook_deliveries` was built for it —
that model's docstring calls itself "M4's delivery log" and carries a
`(merchant_id, created_at DESC)` index nothing read until now.

### 3. Its own credential, its own session table, its own token kind

`merchant_users` gets Argon2 passwords and a `merchant_sessions` table holding
SHA-256 hashes of rotating refresh tokens. The JWT carries the kind
`merchant_access`, and the kinds reject each other: a customer `access` token
presented here is refused, and a `merchant_access` token presented to
`/api/v1` is refused.

Reusing the customer `users` table was the obvious saving and the wrong one. A
merchant operator is a role inside a company, not a person buying a game
top-up; merging them would mean one row that is sometimes a customer with a
wallet and sometimes an operator with a deposit, and every authorisation check
downstream would have to ask which. The kinds exist so that the answer is
structural rather than a field somebody remembers to read.

### 4. Tokens in `localStorage`, accepting what that costs

The cabinet is a different origin from the API, so a cookie would need
third-party semantics that browsers are actively removing. `localStorage` is
the honest alternative, and the trade is real: an XSS on `reseller.yupay.uz` can
read the tokens.

The mitigations are the access token's 15 minutes and a refresh that
**rotates** — a stolen refresh works once, and the theft surfaces as the real
operator's next refresh failing rather than as silence. The origin split in
§1 is what keeps the attack surface to this app's own code.

### 5. The cabinet is **not** exempt from the coarse rate limit

`/merchant/v1` is on `bootstrap._exempt_self_authenticating_routes` because a
429 to a signing acquirer costs money and buys nothing (AGENTS.md §9). A
password form is the opposite case: it is exactly what a per-IP limit is for.
So `/merchant/cabinet` carries the ordinary limit, and its two credential
routes carry the two-axis Redis `ip_guard` besides.

## Consequences

**Positive**

- Onboarding stops being a support conversation. A reseller can reach a first
  order, rotate a leaked key at 3am, and re-enable their own auto-disabled
  webhook, without waiting for our morning.
- The offer acceptance is a **record**, not a checkbox: `offer_version` and
  `offer_accepted_at` are written together under
  `ck_merchant_users_offer_complete`, and the cabinet shows both back.
- The wholesale price list a person browses and the JSON their server polls
  come from one builder (`price_list.build`), so the two can never disagree
  about what is sellable or what it costs.

**Negative**

- Another Next.js app to build, deploy and keep in dependency lockstep.
- A second password surface to defend, with its own reset and confirmation
  flows to write.
- `merchant_cabinet_url` must be configured before registration works at all —
  without it the confirmation link cannot be built, and `register` refuses
  rather than creating an account whose mail can never arrive.

## Validation

The cabinet is correct when a reseller who has never spoken to us can register,
confirm, accept the offer, place an order and read it back — and when the
money on the Orders list, the statement and the dashboard balance are the same
number. The last part is what the integration tests assert and what a browser
pass over a seeded merchant confirmed: $250.00 credited, three orders, $183.84
left, agreeing on all three screens.

## References

- `apps/api/src/yupay/modules/merchants/README.md` — the machine contract
- [ADR-0068](./0068-merchant-b2b-foundation.md), [ADR-0069](./0069-merchant-machine-api.md)
- [ADR-0075](./0075-merchant-unit-priced-orders.md) — the pricing the catalog page shows
- `docs/runbooks/merchant-b2b.md` — operating it
