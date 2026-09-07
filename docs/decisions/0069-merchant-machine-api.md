# 0069 — The merchant machine API: its own version, a signed request line, and no single-use marker

- Status: accepted
- Date: 2026-09-07
- Spec: `docs/superpowers/specs/2026-09-06-merchant-b2b-design.md`
- Plan: `docs/superpowers/plans/2026-09-07-merchant-b2b-m2.md`
- Predecessor: ADR-0068 (the M1 foundation this builds on)

## Context

M2 turns the merchant entity into a surface a stranger's server calls:
`/merchant/v1` — authenticate, read a priced catalog, place an order against a
prepaid deposit, read that order back. It is the first API in this repo whose
consumer we cannot redeploy, which changes what a mistake costs and is the
thread running through every decision below.

The contract itself lives in
`apps/api/src/yupay/modules/merchants/README.md` — that file is what third
parties implement against, and it is deliberately not duplicated here. This
ADR records the six choices a future maintainer would otherwise re-litigate.

## Decisions

### 1. `/merchant/v1` is versioned independently of `/api/v1`

The router carries its own prefix and is mounted by `bootstrap`, not by
`api/v1`. It has its own auth scheme, its own error vocabulary and its own
audience, and hanging it off the storefront's version number would tie two
release cadences together for no reason: `/api/v1` moves when our own web and
mini-app move, which is often and on our schedule.

**A breaking change here costs a `/merchant/v2`, never an edit.** Inside `v1`,
fields may be **added** to any response; nothing is renamed, retyped or
removed, and no request field becomes required. This is not a style preference
— the storefront can absorb a rename in the same deploy that ships it, and a
reseller's integration cannot, because nobody but its owner can redeploy it.
The DTOs live in their own file (`machine_schemas.py`, apart from the admin
SPA's `schemas.py`) so the difference in what a change costs is visible from
the filename before anyone opens it.

### 2. Merchant pricing reaches the order path through a keyword argument, not a fork

`orders.create_order` grew one merchant-only parameter,
`unit_price_usd_override`, carrying the wholesale price `merchants.pricing`
computed. The alternative — a B2B `create_order` of its own — is how two
surfaces start disagreeing about qty rules, `fulfillment_data` validation or
which statuses exist, and that disagreement is only ever found in production.

The seam is guarded on both sides, in `_check_merchant_only_arguments`:

- the override with a non-merchant actor **raises**, rather than being
  silently ignored. A client-supplied price arriving on a retail order is the
  one thing this seam must never become, and
  `test_a_retail_actor_cannot_inject_a_unit_price_through_the_same_door` is
  the test that keeps it from becoming it;
- an `affiliate_code` on the merchant arm raises too. `resolve_code` takes
  `user_id=actor.user_id`, which is NULL for a merchant, so a code would
  resolve like a guest's and take a retail discount off an already-wholesale
  price.

`test_a_retail_order_without_an_override_still_pays_the_retail_price` pins the
other half: the seam is inert when nobody uses it.

### 3. The signature covers the raw request line

`HMAC-SHA256(secret, canonical)` where

```
canonical = {timestamp}\n{METHOD}\n{raw_path}\n{raw_query}\n{sha256_hex(body)}
```

and `raw_path`/`raw_query` are the bytes **as they appear on the request
line**, percent-encoded, read from `scope["raw_path"]` / `scope["query_string"]`.

Raw, and five fields, for one reason: a percent-encoded field cannot contain a
literal LF, so no request can smuggle a newline into one field and have a
verifier read it as the start of the next. The body is included as a
fixed-width hash for the same reason. Every field is therefore either
LF-free or fixed-width, and two distinct requests cannot produce identical
signed bytes.

**The earlier four-field form signed the decoded path and was safe only by
accident** — CPython's `urlsplit` happens to strip control characters, so an
attacker could not get an LF into the decoded path _on this runtime_. An
accident of a standard-library implementation is not a control, and it is
exactly the kind that survives a review and dies on an upgrade.

Signing the encoded form also settles how a path segment the merchant chooses
(`merchant_order_id`, which may contain `/`) is spelled: there is one byte
string on the wire and both sides sign it. And it puts the query string under
the signature, which matters because `?limit=10` and `?limit=100000` are
different requests and the edge access log records the query verbatim.

### 4. The secret is encrypted at rest, not hashed

An HMAC cannot be verified without the key material. A one-way digest either
forbids request signing outright or forces the digest itself to become the
signing key — which is storing key material in the clear under a reassuring
name. So `merchant_api_keys` holds `secret_enc`/`secret_nonce`
(XSalsa20-Poly1305 via `core/crypto.py`, purpose
`yupay:merchants:apikey:v1`), and migration 0070 replaced 0065's
`secret_hash`. The table was empty in every environment, so there was no
backfill and no integrator to break. Spec §9.2's "stored hashed" is superseded
by this.

The argument that settled it: **this repo already encrypts voucher codes with
the same primitive.** A voucher code is worth one SKU; a signing key is worth
every dollar of a merchant's deposit. Refusing the same protection to the more
valuable secret would have needed a reason, and there wasn't one.

Honest boundary, stated in the module README too: a stolen dump alone yields
nothing usable, and an attacker holding both the dump and the application key
is exactly as well off as if the secret were plaintext. What bounds that is
revocation and the per-key IP allowlist, not the cipher. `core/crypto.py`
derives a per-purpose key by HKDF from one input (`INVENTORY_ENC_KEY`), so
voucher codes and merchant secrets never share a key — and that one input is
now load-bearing for two subsystems, which the runbook covers.

### 5. Signatures are **not** single-use

A `SET NX` burn marker made each signature single-use for one commit, and was
reverted. The reasoning is worth keeping because it looks like a security
regression until you follow it through: **a replaying attacker and a retrying
client send byte-identical requests.** No server-side marker can separate
them, so single-use buys no replay protection — it only converts a network
fault into an auth error, on the money path, where the first attempt may
already have created an order the caller can then never learn about. Our own
edge makes that likelier than average: deploys are stop-then-start, which is
why the Caddyfile carries `lb_try_duration` at all. Neither AWS SigV4 nor
Stripe single-uses a signature.

Replay is bounded by three things instead, each somebody's job:

- **the ±300 s window** (`merchants.auth`), which caps how long a captured
  request stays usable;
- **keeping credentials out of the access log.** Caddy redacts `Authorization`
  and nothing else, so `X-Merchant-Key` and `X-Merchant-Signature` were being
  written verbatim to a log promtail ships to Loki. `infra/caddy/Caddyfile.prod`
  now deletes both. That was the capture vector the marker was reaching for,
  closed where it actually lives;
- **idempotency, for mutations.** `merchant_order_id` makes a replayed order
  harmless, which is what makes it **load-bearing rather than a convenience**:
  it is the only thing standing between a replayed `POST /orders` and a second
  debit. It is also why that endpoint takes no `Idempotency-Key` header — a
  header key is minted per attempt by our client, `merchant_order_id` is
  minted per intent by theirs, and offering both would give an integrator two
  ways to be idempotent with one of them wrong. AGENTS.md §9 records the
  exception.

A replay inside the window by somebody who can observe traffic is **accepted**,
and the README says so in those words rather than implying otherwise.

### 6. The merchant order path forces asynchronous fulfilment at the call site

`merchants/orders.py::_enqueue_only` hands `fulfillment.start_for_order` a
settings copy with `fulfilment_async` on, regardless of the deployment's flag
— which defaults off and is off on production.

It is a call-site decision and not an operator's because with the flag off,
`start_for_order` runs the **supplier purchase inside the transaction that
debits the deposit**. `process_task` catches `FulfillerError` and
`FulfillerNotIntegratedError` and nothing else, so anything raising after the
supplier is paid and before the commit rolls back the order, the debit, the
task and the delivery while the supplier keeps the money — and the merchant,
following our own published contract, retries the same `merchant_order_id`,
finds nothing, and buys it a second time. AGENTS.md §10 forbids synchronous
external HTTP on the request path for this reason.

The two failure modes are not comparable: a stalled worker leaves an order
visibly `fulfilling` with the money correctly debited and every row present and
recoverable. And enqueue-only was contract-compatible from the start — the
endpoint already answers `status: "fulfilling"` and already tells resellers to
poll — so nothing on the wire changed.

### 7. The RFC 7807 validation handler is scoped to this prefix, not app-wide

`RequestValidationError` — anything a request schema refuses before our code
runs — answered FastAPI's `{"detail": [ … ]}`: `application/json`, no `type`,
no `code`, from endpoints whose error table decision 1 makes a published
contract. `core.errors.problem_json_validation_handler` renders those as
problem+json with `code: "invalid_request"`.

It is registered app-wide and **delegates to FastAPI's own handler for every
path outside `/merchant/v1`**, byte for byte. Replacing the body everywhere
looks like the simpler change and is the wrong one: FastAPI documents every
route's 422 as `HTTPValidationError` and `packages/api-client` types every
operation in the repo from that schema, so changing the runtime body without
changing the schema would make the generated client wrong nearly everywhere —
and `openapi-drift` could not catch it, because the schema would not have
moved. For this prefix the schema _does_ move
(`machine_routes._VALIDATION_PROBLEM` overrides the 422 response), so the
document and the client follow.

Two details that are load-bearing rather than incidental:

- `exc.errors()` goes through `jsonable_encoder`, not `json.dumps`. A
  `value_error` entry carries the original exception **object** under
  `ctx["error"]`; a naive handler raises `TypeError` and turns a clean 422 into
  a 500 — on a non-UUID `sku_id`, which is among the likeliest integrator
  mistakes.
- `detail` stays a **string** and the per-failure list moved to a new `errors`
  key. Retyping `detail` from string to array would contradict every other
  error this API returns, and decision 1 makes that a `/merchant/v2` rather
  than an edit — which is why it landed now, at zero integrators.

## Consequences

- **The merchant channel depends on the worker being up, always.** Turning
  `FULFILMENT_ASYNC` off does not return merchant orders to inline fulfilment,
  and must not be attempted as a way to do so
  (`docs/runbooks/fulfillment-queue.md`).
- **`INVENTORY_ENC_KEY` is now load-bearing for a second subsystem.** Rotate or
  lose it and every merchant API key stops verifying: the auth path logs
  `merchant_api_key_undecryptable` and answers an ordinary `401`, so the
  failure is diagnosable but not self-healing. Recovery is revoke-and-reissue
  — see `docs/runbooks/merchant-b2b.md`. The variable's name is narrower than
  its job now; a neutral rename (`APP_ENC_KEY`, with the old name as a
  deprecated alias for one release) is a follow-up.
- **The Caddy access-log redaction must be deployed before a merchant sends a
  real signature**, and editing `Caddyfile.prod` on the host needs
  `up -d --force-recreate caddy` (single-file bind mount; `caddy reload`
  re-reads a stale inode).
- **`/merchant/v1` is exempt from the coarse slowapi limiter**
  (`bootstrap._exempt_self_authenticating_routes`). Its own two-axis guard
  answers RFC 7807 with a `Retry-After`; at equal ceilings (600/60 s both) the
  middleware would otherwise win the tie on a polling caller and return a body
  with no `type` and no `code`, from an endpoint whose error contract we
  published.
- **M3 must register `/merchant/v1/orders/{id}/refund` above the order read.**
  That route uses Starlette's `:path` convertor, which compiles to `.*` and
  swallows the whole subtree; Starlette takes the first full match in
  declaration order.
- The ±2% price-drift rule is spec §8.4 implemented as written, and it lets a
  merchant quote 2% low on every order. It is recorded at
  `pricing.price_to_charge` and in the runbook's known-gaps section; changing
  it is one line, and it is the owner's call, not a maintainer's.
