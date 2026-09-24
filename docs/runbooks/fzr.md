# Runbook — FazerCards (api.fzr.cards)

> Slug `fzr`. A **reserve** supplier, like NOVA: nothing routes here on its own.
> An operator switches a SKU with `force_supplier` and switches it back the
> same way.
>
> **Read `nova.md` first for anything about the protocol.** FazerCards
> publishes the same panel v2 API NOVA does — the same paths, the same `{ok, …}`
> envelope, the same per-category `fields` declaration, the same
> charge-on-create behaviour. Everything in `nova.md` about lost creates, gift
> cards being a second endpoint, sold-out cards, and «Field "…" is required»
> applies here unchanged. This file is only what is **different**.

## Why it exists

Price. Measured against our own catalogue on 2026-09-24:

- on **38 of the 39** SKUs we buy from NOVA, FazerCards quotes exactly
  `nova_price / 1.02` — a flat 2% under, with no exceptions worth the name;
- weighted by 30 days of real delivered volume, it is about **$27/month**
  cheaper than the best price we already hold across g2b, gengine and nova;
- their Steam wallet rebate is **3.55% at Gold** against NOVA's confirmed 2%,
  worth about **$25/month** on our measured $1,620.97 of 30-day Steam volume.

Against that, the subscription (below) and an account with no delivery history.

## The subscription — the thing that is not like the others

**Every other supplier is a key. This one is a key plus a monthly plan**, and
the plan gates both the catalogue and the Steam rebate.

| Plan   | API says | their `llms.txt` (2026-07) | Steam rebate |
| ------ | -------- | -------------------------- | ------------ |
| bronze | $3.99/mo | $9.99/mo                   | ≈ 2.5%       |
| silver | $6.99/mo | $19.99/mo                  | ≈ 3%         |
| gold   | $9.99/mo | $29.99/mo                  | 3.55%        |

The two columns disagree and we could not settle it — `activation-quote`
refuses while a subscription is active. `GET /api/v2/subscription/plans` is the
live number for **our** account; treat `llms.txt` as possibly stale, and check
the panel before assuming the cheaper one.

**Our account is on a 5-day Gold trial that expires 2026-09-29.** After that,
without a paid plan, every product route answers:

```json
{ "ok": false, "error": "…", "code": "subscription_inactive" }
```

with HTTP 403. The adapter turns that into a task error that says
**«fzr subscription is not active — renew the plan in their panel»** rather
than an anonymous 403, and grades the money `RETURNED` — nothing was charged.

The admin's supplier health card (`GET /admin/integrations/fzr/health`) shows
`plan`, `plan_expires_at` and `subscription_active` beside the balance, so
"can we still route here tomorrow" is answerable without a shell.

### What the plan does and does not change

Only three things are priced per plan, and their OpenAPI says so in exactly
three places: **Steam wallet top-up**, **Steam gifts**, and **manual
services**. The top-up and gift-card catalogues this integration buys from are
not described as plan-adjusted, and the flat 1.0200 ratio against NOVA across
39 products from 8 brands is consistent with that.

So: the ~$27/month on games should hold on any plan; the ~$25/month on Steam
is Gold's.

## Funding

**Crypto only.** `GET /api/v2/payments/methods` lists USDT on TRC20, BEP20,
TON and Aptos, minimum $3, maximum $5,000. Their marketing also mentions
Binance Pay and cards; the API does not offer them.

There is no overdraft: the balance is debited on create, and an order that
outruns it is refused with `Insufficient internal balance`, which the adapter
grades as the soft low-balance failure — the customer keeps waiting, the task
parks in the admin inbox, and ops get the throttled Telegram alert with both
`Баланс:` and `Нужно:` filled in.

## Rate limits — published, unlike NOVA's

Per API key, per **category of operation**, on independent sliding windows.
Exceeding one returns 429 for that category only, with `Retry-After` in
seconds.

| Category       | Limit     | What of ours lands here                          |
| -------------- | --------- | ------------------------------------------------ |
| Create order   | 60 / min  | every `fulfill`                                  |
| Order status   | 120 / min | every reconciler poll                            |
| Catalogue read | 120 / min | the hourly sync, and one `get_offers` per order  |
| Account read   | 30 / min  | the balance probe on a low-balance alert, health |
| Other          | 120 / min | —                                                |

Our sweeps are far under all of these, which is why **no client-side throttle
ships with this adapter**. If one becomes necessary it belongs in
`panel_client`, not in `fzr.py`.

A 429 is graded `RETURNED`: it is rejected at the edge, before anything is
debited. That is a deliberate difference from a 409 or a 5xx, both of which
stay `UNKNOWN`.

## Idempotency — where their documentation and NOVA's behaviour differ

Their docs are explicit: _"retrying the same request with the same key returns
the original order instead of charging or fulfilling again."_ NOVA's docs say
the same thing and its **live API does the opposite** — `409 This
Idempotency-Key was already used for a purchase`.

**We have not verified FazerCards' actual behaviour**, because doing so means
placing two real orders and the account has no balance. Until someone does,
the adapter treats a 409 the cautious way: undecided, not a free retry, and a
lost create is parked for adoption rather than retried.

**If you verify it**, write the result here. If a repeat really does replay,
the safe simplification is to retry a lost create under the same key instead of
adopting, which removes a whole failure mode.

## What is deliberately not wired up

**Telegram.** Their `POST /api/v2/telegram/stars/buy` and
`/telegram/premium/buy` exist and would fit the adapter, but on 2026-09-24 they
quoted **$0.0152625 per Star against NOVA's $0.015225**, and were dearer on all
three Premium terms (3 / 6 / 12 months). Routing Telegram here would cost us
money. The branch is absent rather than present and unused; add it if that
inverts.

**Game keys, Steam gifts, manual services, their webhooks.** Not needed for the
measured saving. Their webhook (`order.completed` / `order.failed` /
`order.refunded`, configured in their hub, signed) would replace our polling
and is the obvious next step if this supplier earns a permanent place.

## Steam — two ways to buy it, and they are different products

|          | NOVA today    | fzr wallet top-up | fzr `steam_cis` gift card       |
| -------- | ------------- | ----------------- | ------------------------------- |
| discount | 2%            | 3.55% at Gold     | 3.55% (`100 USD` → `96.4500`)   |
| how      | login, direct | login, direct     | a **code** the customer redeems |
| amounts  | any           | any               | fixed 1…100 USD                 |
| region   | —             | —                 | CIS account required            |

Our `steam-wallet-usd` SKU is variable-amount and credits a login, so the
**wallet** path is the drop-in replacement — map it with the sentinel
`steam-topup` (no category, no denomination, exactly as NOVA's) and the adapter
sends `steamLogin` + the face value. What it costs us comes back as the debit
beside the order and lands in the task metadata as `supplier_charged_usd`.

The gift card is cheaper to reason about but changes the customer's
experience from "we topped you up" to "here is a code, and it must be a CIS
account". Do not switch to it without deciding that is wanted.

## Switching a SKU to fzr and back

Identical to NOVA's procedure in `nova.md` — `force_supplier: fzr` on the
sourcing rule — with two extra checks before you do it:

1. **Is the plan paid?** Health card, `subscription_active`.
2. **Is there balance?** Health card. It is $0.0000 as of 2026-09-24.

Switching re-prices the SKU immediately (ADR-0091), so the shelf price follows
the new cost on the next read.

## First live order — NOT YET DONE

Nothing has been bought here. Until one order has gone through, record below:

- the real keys of their order object and the statuses it walks;
- whether a repeat with the same `Idempotency-Key` replays or 409s;
- whether their gift-card create returns `cards: []` and fills them in on the
  order a second later, as NOVA's does;
- how long `processing` lasts in practice.

`fzr.unknown_order_status`, `fzr.order_without_status` and
`fzr.order_without_id` in the logs are the signal that our guesses were wrong.

## What the logs say

Same event names as NOVA's, prefixed `fzr` instead. The ones worth knowing:

| Event                                      | Level | Meaning                                                                            |
| ------------------------------------------ | ----- | ---------------------------------------------------------------------------------- |
| `fzr.request`                              | info  | One API call — method, path, status.                                               |
| `fzr.unknown_order_status`                 | warn  | A status outside the allow-list; still `in_progress`. The first-live-order signal. |
| `fzr.order_without_status` / `_without_id` | warn  | Their order object had no recognisable `status`/`state` or `id`.                   |
| `fzr.giftcard_completed_without_codes`     | warn  | Charged, marked complete, nothing to hand over. Reconcile by hand.                 |
| `fzr.field_spec_unavailable`               | info  | `get_offers` failed; the order went out under the legacy rename.                   |
| `fzr.balance_unavailable_for_alert`        | info  | The low-balance alert lost its `Баланс:` figure. Harmless.                         |
| `fzr.subscription_unavailable`             | info  | The health card lost its plan half. Harmless.                                      |
| `fzr.adopted_order`                        | info  | A lost create's order was found and adopted.                                       |

## Related

- `docs/runbooks/nova.md` — the protocol, in full. Read it first.
- ADR-0092 — why FazerCards, and why the shared panel layer.
- ADR-0081 — reserve suppliers and why nothing routes to one automatically.
- ADR-0091 — a route change re-prices immediately.
