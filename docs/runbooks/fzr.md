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

**Our account is on a 5-day trial that expires 2026-09-29.** Note the
mismatch: `GET /api/v2/subscription` reports `plan: "trial"`, while their
marketing calls it a _Gold_ trial. The `steam_cis` card prices at exactly
`96.4500` per `100 USD` — 3.55%, the Gold rate — which is consistent with a
trial that grants Gold pricing, but it is consistency, not their word. **So
every price we measured is a trial price**, and none of it is confirmed to
survive onto a paid plan. Confirm against the panel before committing to a
tier.

After the trial, without a paid plan, every product route answers:

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

## Idempotency — they replay, unlike NOVA

Both vendors' docs say a reused key "returns the original order". Only
FazerCards means it.

Measured 2026-09-24: one `POST /giftcards/order` sent **twice** under a single
`Idempotency-Key` answered `200` both times with the same `ord-1549395`, the
order completed with one code, and the balance moved once. NOVA, on the same
engine, answers `409 This Idempotency-Key was already used`.

What that buys:

- **Retry works.** `fulfillment.service.KEY_BURNED_ON_USE` excludes `fzr`, so
  a retried task reuses its key and gets its own order back. On NOVA the same
  press needs a fresh nonce or it 409s for ever — which is the whole reason
  that set exists.
- A lost create could, in principle, be recovered by re-sending it rather than
  by adoption. We do not: `panel_adopt` is built, tested and vendor-neutral,
  and a second create from a status check would be a stranger thing to reason
  about than a search.

A 409 is still graded undecided. That branch now means "the vendor is behaving
unlike itself", which is precisely when caution earns its keep.

## What is deliberately not wired up

**Telegram.** Their `POST /api/v2/telegram/stars/buy` and
`/telegram/premium/buy` exist and would fit the adapter, but on 2026-09-24 they
quoted **$0.0152625 per Star against NOVA's $0.015225**, and were dearer on all
three Premium terms (3 / 6 / 12 months). Routing Telegram here would cost us
money. The branch is absent rather than present and unused; add it if that
inverts.

**Game keys, Steam gifts, manual services.** Not needed for the measured
saving.

## The webhook

Built 2026-09-24. Polling still runs underneath it, so a missed event costs
latency, not an order.

**URL to enter in their panel (Settings → Webhook):**

```
https://api.yupay.uz/api/v1/webhooks/fzr
```

Saving it there generates the secret in the same panel section. Put that in
`secrets/api.env` as `FZR_WEBHOOK_SECRET` and restart api. **Until it is set
the receiver rejects every delivery** — it fails closed on purpose, because a
receiver that accepted unsigned bodies would look like it was working.

How it behaves, and why:

| their side                                             | ours                                                              |
| ------------------------------------------------------ | ----------------------------------------------------------------- |
| `X-Webhook-Signature: sha256=<hmac>` over the raw body | verified **before** the JSON is parsed (§9)                       |
| `order.status_changed`                                 | the task is marked due; the sweep does the asking                 |
| `order.created`, `manual_service.chat.*`               | `200`, ignored — we created it, and we don't sell manual services |
| an order we never placed                               | `200 unknown_order`                                               |
| a task that already finished                           | `200 already_final` — a normal race with the sweep                |
| a body we cannot parse                                 | `200 ignored`                                                     |
| a delivery older than an hour                          | `200 ignored, stale`                                              |
| a body over 64 KB                                      | `413`, refused before it is read                                  |
| a bad signature                                        | `401`                                                             |

Everything but the last two answers `200` deliberately. They retry a non-2xx
three times (1 min, 5 min, 30 min) and **disable the webhook after 50
consecutive failures**, so an honest `404` for an unknown order would, fifty
orders later, silently switch the feature off.

**The handler never calls FazerCards.** It verifies, finds the task, clears
`next_attempt_at` and answers — the status check runs on the sweep. Doing it
inline would hold an API pool connection for up to the 20-second request
timeout, and the pool is 10 + 10: twenty concurrent deliveries would take the
whole API down. That is not hypothetical here (`QueuePool limit of size 10
overflow 10 reached`, 2026-09-23), and their own documentation asks for it
this way: _"Respond quickly (200 within seconds); do heavy work
asynchronously."_ The cost is at most one sweep tick.

The freshness window is an hour and not tighter **because their retry carries
the original timestamp**: anything under ~36 minutes would refuse their own
third attempt and spend one of the fifty.

Rotating the secret in their panel invalidates the old one **immediately** —
update `secrets/api.env` first, then rotate, or deliveries fail in between.

Check `GET /api/v2/account/webhook/deliveries` (last 50) or their panel when
something looks stuck; `fzr.webhook.*` in our logs is the other half.

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

## The reconcile sweep

`fulfillment.fzr_reconcile`, every 10 seconds, in the scheduler process. It is
what actually finishes orders: their create answers `processing` and charges
immediately, so **without it an order sits `in_progress` for ever** — no
error, no alert, a customer on "в обработке" and the money already gone.

It shares its implementation with NOVA's (`panel_reconcile`), and the cadence
is not as aggressive as it sounds: a task younger than two minutes is
rechecked every 10 s, older than that every 60 s. The webhook's job is to
collapse that 60 back to 10 for an order somebody is waiting on.

## Switching a SKU to fzr and back

Identical to NOVA's procedure in `nova.md` — `force_supplier: fzr` on the
sourcing rule — with two extra checks before you do it:

1. **Is the plan paid?** Health card, `subscription_active`.
2. **Is there balance?** Health card. It is $0.0000 as of 2026-09-24.

Switching re-prices the SKU immediately (ADR-0091), so the shelf price follows
the new cost on the next read.

## First live orders — done, 2026-09-24

Seven orders between 08:46 and 09:32, **all succeeded**, nothing reconciled by
hand. What they settle:

| question                    | answer                                                                                              |
| --------------------------- | --------------------------------------------------------------------------------------------------- |
| order id shape              | `ord-1547700` — `ord-` + digits, as documented                                                      |
| statuses walked             | `processing` -> `completed`. Both already in the allow-list; `fzr.unknown_order_status` never fired |
| events sent                 | `order.created`, then one or two `order.status_changed` (13 events for 7 orders)                    |
| Steam rebate, in production | **exactly 3.55%**: 15.00 -> 14.4675, 6.00 -> 5.7870, 3.00 -> 2.8935, 1.00 -> 0.9645                 |
| delivery time               | Steam ~1.5-2 min; a PUBG top-up 16 s                                                                |
| webhook health              | 22 deliveries, **0 failures**, 324-749 ms each                                                      |

Two things worth knowing that the table does not say.

**A game order carries no debit.** `supplier_charged_usd` is filled for every
Steam line and empty for the PUBG one: their create returns a `*Debit` block
for Steam, where the plan rebate makes the charge differ from the amount, and
not for a catalogue offer, where it does not. That is correct, not a gap.

**All seven ran on the synchronous webhook**, the one that reconciled inline —
it was replaced at 09:42 with the version that marks the task due and lets the
sweep ask. So the _current_ path has not yet carried a real order. It is the
same `check_status` either way, a tick later; the thing to watch on the next
order is simply that it finishes, and `fzr_reconcile.tick` showing a non-zero
`failed` is the signal if it does not.

**The idempotency contract is settled too** — see its own section above. A
reused key replays here, so `KEY_BURNED_ON_USE` excludes fzr on evidence
rather than on their word.

## Genshin's server field — fixed 2026-09-25

Order `01a0d68a` (Blessing of the Welkin Moon) was refused with
`Field "server": value must be one of the allowed options` and fulfilled by
hand. Our Genshin form stores HoYoverse's region codes — `os_usa`, `os_euro`,
`os_asia`, `os_cht` — because G2B, the primary route, keys on them. fzr and
NOVA both declare `america` / `asia` / `europe` / `tw_hk_mo` for
`genshin_impact_global`, and no option's value or label matches a code, so
`os_usa` went out verbatim. Every Genshin order routed to either vendor would
have failed the same way; this was the first.

`panel_fields._REGION_ALIASES` now tries the code's word when nothing else
matches, and only if that word is one of **their** options. Checked against
both vendors' live declarations: all 32 form-option × product × vendor pairs
(Genshin and Honkai Star Rail — the only select fields we route to either)
land on an allowed value. Honkai never hit this: its form already stores the
words.

If `panel.option_not_in_enum` appears in the logs, a form value has no match
again — the log line carries the value, and the refusal will name the field.

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
