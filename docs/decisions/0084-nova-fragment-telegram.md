# 0084. NOVA's Fragment API for Telegram Stars and Premium

- **Status**: Accepted
- **Date**: 2026-09-20
- **Deciders**: owner, Claude
- **Tags**: backend | integrations

## Context and problem statement

Telegram Stars and Premium reached G-Engine and nobody else. Both are brands with real
volume, and a single channel means a supplier's bad hour is our outage — the same argument
[ADR-0081](./0081-nova-reserve-supplier.md) made for game top-ups.

[The NOVA design doc](../superpowers/specs/2026-09-17-nova-supplier-design.md) put "Telegram
Stars / Premium (they have a separate Fragment API namespace)" explicitly out of scope. This
ADR brings it in, and records what reading that API actually taught us.

Three suppliers, priced 2026-09-20:

|                      | Premium 3 / 6 / 12              | One Star     | Free-amount Stars      |
| -------------------- | ------------------------------- | ------------ | ---------------------- |
| G-Engine (incumbent) | 12.8413 / 17.1253 / 31.0483     | 0.015455     | yes                    |
| G2B                  | 12.23 / 16.31 / 29.57           | 0.0153       | **no** — packages only |
| **NOVA**             | **12.1699 / 16.2299 / 29.4249** | **0.015225** | **yes**                |

NOVA is cheapest on every line, and is the only alternative that can serve the free-amount
Stars SKU — which is the one the storefront actually renders, packages being drawn from the
per-Star price.

## Decision

Add a NOVA Fragment client, a fulfilment branch and a cost lookup, behind two new sentinels.

### The Fragment API agrees with NOVA's v2 API on almost nothing

Verified against their published spec (`/api/openapi.json`) and by calling the quote
endpoints:

- **No `ok` envelope.** A Fragment 200 is the payload. `NovaClient._request` refuses anything
  without `ok: true`, so every successful Fragment call raised through it — hence a separate
  `_fragment_request` rather than a new method on the old path.
- **A reused `Idempotency-Key` returns the original order**, the exact opposite of the v2
  endpoints, where a repeat is refused with `409` (which cost us a stuck task the day before —
  see `arm_retry_key`). One supplier, two contracts.
- **A quote is not a validation.** `premium/quote` priced `@zz_no_such_user_zz_41907` and
  echoed it back as `recipient`. It is a calculator. Anything that needs to know a username is
  real must ask elsewhere — today only G2B answers that, which is its own piece of work.
- Statuses are `PREPARING…SUCCESS/FAILED/REFUNDED` plus **`DRY_RUN`**, which the existing
  grader would have read as an unknown word and left in flight, waiting for a delivery that is
  never coming. It is graded a failure that cost nothing.

### Sentinels, not a fourth mapping kind

`fragment-stars` and `fragment-premium` follow `NOVA_STEAM_SENTINEL` exactly, for the reason
0081 records: `ck_sku_supplier_mapping_kind` allows only `voucher|game|gift`, and the admin
wizard round-trips an unknown `external_product_id` untouched while it would coerce a new kind.

`fragment-stars` carries no variant and is exempt from the "a game mapping needs one" check;
`fragment-premium` is deliberately **not** exempt, because its months _are_ the variant and the
three products differ by nothing else.

### One counter, not two

The star count is not computed in the NOVA adapter. G-Engine's `_quantity_for` moved to
`suppliers/amount.py` as `quantity_for`, unchanged, and both adapters call it. A package SKU
carries its pack size on the mapping and is bought `qty=1`; the free-amount line carries `1`
and arrives with the customer's own count as `item.qty`. Two adapters reading that row
differently is how somebody gets 1 Star instead of 5000, and the second reader is exactly when
that risk appears.

That move also found a real defect: `fulfill` refused `item.qty > 1` before the mapping was
loaded — correct for a game offer, a Steam wallet and a Premium gift, and fatal for the
free-amount Stars line, whose whole shape is a large `qty`. The guard now runs after the
mapping is known and exempts `fragment-stars` alone.

### Cost, and what the sourcing screen can finally show

Only g2b and nova have a `cost_lookup`, so a Telegram SKU had no live price from anyone.
Stars are linear — 50 quoted at $0.761250 and 1000 at $15.225000 against a per-Star
$0.015225 — so one `GET /stars/price` prices every pack through the mapping's `quantity`, and
the free-amount line's `1` yields the per-Star cost with no special case. Premium has no such
constant and is quoted with a **placeholder username**: the quote ignores the recipient
(proved above), so sending a real customer's handle to learn a price that does not depend on
it would be worse.

## Consequences

- Routing does not move. NOVA is a reserve; these mappings make it reachable by an explicit
  `force_supplier` and give the comparison something to compare.
- `customer_amount_usd` joins `chargedUsd`/`charged_usd` as a charge field, so a Telegram line
  filled by NOVA records a real cost basis (ADR-0082's point, a third endpoint later).
- Username validation is **not** included and is not available from NOVA at all. Until it is
  built on G2B, a typo'd handle is discovered by the supplier, not by us.
- The mapping seed cannot run until this code is deployed — it imports the sentinels.
