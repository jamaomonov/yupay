# 0092. FazerCards, and one wire format for two vendors that publish it

- Status: accepted
- Date: 2026-09-24
- Deciders: owner, engineering
- Extends: [ADR-0081](./0081-nova-reserve-supplier.md) (reserve suppliers),
  [ADR-0082](./0082-nova-steam-and-real-cost-basis.md) (the Steam sentinel),
  [ADR-0083](./0083-routed-supplier-cost-and-price-ratchet.md) (who writes cost)

## Context and problem statement

An evaluation of FazerCards (`api.fzr.cards`) as a supplier turned up something
the evaluation was not looking for: **it is the same API as NOVA.**

Measured on 2026-09-24, not inferred:

- all twelve `/api/v2` paths our NOVA client calls exist on FazerCards under
  identical names, with the same `X-API-Key` header, the same `{ok, …}`
  envelope, the same `meta.next_cursor` paging, the same
  `offers`-not-`items` quirk on `/giftcards/cards`, and the same
  per-category `fields` declaration;
- on **38 of the 39** SKUs we buy from NOVA, FazerCards quotes exactly
  `nova_price / 1.02` — median 1.0200, minimum 1.0200.

Whether one white-labels the other, or both resell a third party, is not
visible from outside and does not change the engineering question. The
engineering question is what to do with ~100 KB of NOVA adapter when a second
vendor speaks the same protocol.

Weighed against the cost of doing anything at all, the money:

|                                                                  | per month                                            |
| ---------------------------------------------------------------- | ---------------------------------------------------- |
| games, against the best price we already hold (g2b/gengine/nova) | +$26.82                                              |
| Steam, 3.55% at Gold against NOVA's confirmed 2%                 | +$25.13                                              |
| their subscription                                               | −$9.99 (see the runbook: the plan price is disputed) |
| **net**                                                          | **≈ $42**                                            |

Measured on 30 days of real delivered volume, not list prices.

The same measurement also found **$53.95/month we are losing on our own
routing** — Genshin sits on g2b at 107.00 where gengine quotes 97.57, and so
on. That is a separate, larger, and free win; it is recorded here because it
is the honest context for a $42 supplier decision, and it is not what this ADR
decides.

## Decision drivers

- Copying the NOVA adapter would duplicate ~100 KB of money-handling code.
  Yesterday's `panel_fields` bug — an unplaceable key falling through to the
  identifier list, so a category asking for `promo_code` would have received a
  customer's `player_id` — would have needed fixing twice.
- Refactoring a live money path to add a second vendor doubles the risk of one
  change. The two must be separable.
- The vendors are _not_ identical. Anything assumed common that is not is a
  silent wrong answer, and the two most dangerous candidates are the
  idempotency contract and the price catalogue.
- A reserve is only worth having if an operator can reach it: mapping, syncing,
  pricing and routing all have to work from the admin, or it is shelfware.

## Decision

### 1. Extract the shared protocol; do not copy the adapter

Four modules now describe the **panel v2 protocol** rather than NOVA:

| module          | what it holds                                                                                    |
| --------------- | ------------------------------------------------------------------------------------------------ |
| `panel_client`  | the wire format — auth, both error envelopes, cursor paging, every endpoint both vendors publish |
| `panel_grading` | reading an order object and an error, and what each says about our money                         |
| `panel_adopt`   | finding an order whose create response was lost                                                  |
| `panel_fields`  | building `fields` from the vendor's own per-category declaration                                 |

`NovaClient` and `FzrClient` are subclasses that set a slug and two exception
types. `nova_grading` binds a `PanelGrader("nova")` and keeps every name
`nova.py` already imported.

The extraction shipped as its own commits, ahead of the new vendor, and NOVA's
230 existing tests passed untouched. That sequencing is the point: if the
refactor had broken something, it would have been visible before a second
vendor was in the picture to confuse the diagnosis.

**The payoff is already visible in coverage**: `panel_grading`, `panel_adopt`
and `panel_fields` sit at 100% from NOVA's tests alone, so FazerCards inherited
tested behaviour rather than needing it re-proven.

### 2. Keep apart the three things that are not shared

- **NOVA's Fragment API** (`/api/v1/fragment/*`) stays in `nova_client` and
  `cost_lookup._nova_raw_price`. It has no `ok` envelope, the opposite
  idempotency contract, and no FazerCards equivalent.
- **The idempotency contract.** Both vendors _document_ that a reused key
  replays, and only one of them means it. NOVA's live API answers `409`;
  FazerCards really does replay (verified 2026-09-24 — one create sent twice
  under a single key, same `ord-1549395`, charged once). Both were measured
  against the live service, so each adapter states its own contract and
  neither inherits an assumption. Both still park a lost create for adoption
  rather than retrying it: correct under either behaviour, and one path
  instead of two.
- **The caches.** The two vendors use the **same category ids for the same
  games**, so the offers cache threaded through the cost refresh stays NOVA's
  (fzr fetches its own) and the stock cache key now carries the supplier.
  Sharing either would serve one vendor's prices or stock as the other's —
  a wrong answer that reads as a right one.

### 3. FazerCards is a reserve, and Telegram is not routed to it

It joins `RESERVE_SUPPLIERS`, so nothing reaches it without an operator setting
`force_supplier`. The account is a trial with no balance and no delivery we
have witnessed; "cheaper on paper" is not "proven to deliver".

Its Telegram endpoints are deliberately **not** wired up. They exist and would
fit, but FazerCards quotes $0.0152625 per Star against NOVA's $0.015225 and is
dearer on all three Premium terms. The branch is absent rather than present and
unused, so nobody has to wonder why it is never taken.

### 4. A 429 means our money is still ours

FazerCards publishes per-category rate limits (60 order creates a minute, 120
status polls, 30 account reads) and rejects a throttled request at the edge. So
`refusal_money` now grades 429 alongside 400/403/404 as `RETURNED` rather than
`UNKNOWN`. Calling a fully recoverable retry "we may have spent" would put it
in front of a human for no reason. NOVA publishes no rate limit and has never
answered one, so nothing regressed for it.

No client-side throttle ships with this. Our sweeps are far under every limit;
if one becomes necessary it belongs in `panel_client`, not in an adapter.

## Consequences

**Good.** One place to fix a protocol bug. A second source for nearly the whole
catalogue at ~2% under our current reserve. The Steam rebate available to
switch to. The admin can map, sync, price, stock and route to it today.

**Bad.** A supplier whose catalogue access **expires**: this is the first one
that is a subscription, and a lapsed plan answers 403 on every product route.
The adapter names that refusal and the health card shows the plan and its
expiry, but it is a new class of thing that can go wrong, and it goes wrong on
a date rather than in response to anything we do.

**Unresolved, and recorded rather than quietly assumed:**

- ~~Whether a reused `Idempotency-Key` replays here.~~ **Settled 2026-09-24**:
  it does. One gift-card create sent twice under a single key answered `200`
  both times with the same `ord-1549395` and charged once. The decision to
  leave `fzr` out of `KEY_BURNED_ON_USE` now rests on a measurement, not on
  their documentation.
- Whether their plan is $9.99 or $29.99 for Gold — their API and their own
  `llms.txt` disagree, and `activation-quote` refuses while a trial is active.
- **Every price in this ADR was measured on a trial account.** Their API
  reports `plan: "trial"`; their marketing calls it a Gold trial, and the
  Steam card prices at exactly the Gold rate, which is consistent but not
  their word. Nothing here is confirmed to survive onto a paid tier.
- Whether the top-up and gift-card catalogues are plan-adjusted. Their OpenAPI
  says only Steam wallet, Steam gifts and manual services are, and the flat
  1.0200 ratio across 39 products agrees, but it is inference, not their word.
- ~~No order has been placed.~~ **Settled 2026-09-24**: seven orders, all
  succeeded, the status allow-list held and `fzr.unknown_order_status`
  never fired. The Steam rebate is exactly 3.55% in production. See the
  runbook for what else those orders answered.

## Alternatives considered

**Copy `nova.py` to `fzr.py` and change the strings.** Fastest, and wrong: it
doubles every future protocol fix, and the adapter is a money path where a fix
applied once out of twice is worse than no abstraction at all.

**Replace NOVA with FazerCards.** The catalogue is the same and 2% cheaper, so
this is the logical end state. It is not today's decision: NOVA is funded and
has delivered; FazerCards is a trial with $0 and nothing delivered. Run both,
route deliberately, and revisit once FazerCards has a delivery history.

**Use their official SDK** (`pip install fazercards`). It would handle auth,
idempotency and webhook signatures. Declined: every other supplier here is a
hand-written `httpx` client, the shared layer already exists and is tested, and
a vendor SDK on the money path is a supply-chain dependency we would have to
audit for less than it saves.
