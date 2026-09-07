# 0031. Storefront player-id check (advisory G2B nickname lookup)

- **Status**: Accepted
- **Date**: 2026-07-16
- **Deciders**: @jamaomonov
- **Tags**: backend | catalog | integrations | frontend

## Context and problem statement

For game top-ups (PUBG Mobile, Mobile Legends, …) the customer types a numeric
player id at checkout. A typo means the top-up is delivered to a stranger's
account and is effectively unrecoverable. G2B exposes a `checkPlayerId` call
that resolves an id to the account's nickname, and YuPay already wraps it
(`games_check_player` on the G2B client) behind an **admin-only** diagnostic
route (ADR-0019). Customers had no way to reach it before ordering.

We want the customer to type an id, tap a "check" button, and see the
nickname it resolves to — catching a wrong id before paying — without adding
a new failure mode to checkout.

## Decision drivers

- Checkout must stay resilient to G2B being down or a game having no checker
  configured — the check is a UX convenience, not a gate.
- AGENTS.md §10 forbids synchronous external HTTP calls in request handlers,
  but the "check → nickname in ~1s" interaction is inherently a live external
  round trip; the admin route already made the same call synchronously.
- The `integrations` module already owns the G2B client and
  `sku_supplier_mapping`; `catalog` must not gain a dependency on it.

## Considered options

1. **Advisory, synchronous, cached endpoint in `integrations`** — one public
   POST route that calls G2B in-request, folds every failure into
   `status="error"`, and caches results briefly in Redis.
2. **Async job + WebSocket/poll result** — matches the general §10 rule (no
   sync external calls in handlers) but turns a "tap and see" interaction
   into a job-status dance for a non-critical, already-fast lookup.
3. **Gate checkout on a valid check** — forces every top-up order through a
   working G2B call, making checkout availability depend on an upstream
   integration.

## Decision outcome

**Chosen option:** Option 1. The check stays advisory (never gates checkout —
see "Non-goals") and reuses the exact synchronous-call shape the admin route
already established, so the deviation from §10 is not new engineering, just a
second call site for a pattern already accepted in production. Option 2 is
rejected as needless complexity for a lookup that is already sub-second and
whose failure is invisible to the order flow. Option 3 is rejected outright —
G2B availability must never become a checkout dependency.

### What blocks Pay, and what never does (amended 2026-08-22)

The storefront later grew a gate on the check, and it was written as
`status !== "valid"` — which quietly turned Option 3 back on, because `error`
is not `valid`. With the check live on a brand, a G2B outage, a 5xx of ours or
a rate-limited buyer left the Pay button dead and no way past it. The rejected
option had arrived by the back door.

The rule the code now holds, in `blocksCheckout` on both storefronts:

| Outcome         | Pay         | Why                                                                                    |
| --------------- | ----------- | -------------------------------------------------------------------------------------- |
| not checked yet | blocked     | the customer has not asked the question                                                |
| `valid`         | allowed     |                                                                                        |
| `invalid`       | blocked     | the provider positively says no such player — this is the typo protection worth having |
| `error`         | **allowed** | our fault or the supplier's, never the customer's                                      |

On `error` the field says the check is unavailable and asks the customer to
re-read what they typed. That keeps the typo protection Option 3 wanted for
the case where an answer exists, without making a sale depend on G2B being up.

### When an answer stops applying (amended 2026-09-04)

The table's first row carries more weight than it looks: an answer about a
_different_ question is "not checked yet". The lookup is scoped to one product
and one id, so on a region-split brand ([ADR-0048](./0048-mobile-legends-region-split.md))
switching package switches product, and the nickname G2B confirmed for the
Russian game says nothing about the global one.

That used to be enforced by a `setState(IDLE)` in a passive effect, with a
second effect mirroring the outcome up to the panel that gates Pay. Passive
effects flush in a later scheduler task, so the commit that switched product —
the one the browser can paint, and the customer can click Pay in — still showed
the green "verified" pill for the other region **and** still held its `valid`
upstream. Fail-open, in the one direction the gate exists for.

The web storefront now stores the verdict together with the product + id it
was asked about, and reads it back through a render-time derivation
(`currentCheck` in `player-check-state.ts`), reported straight from the check
handler rather than from an effect. Going stale is therefore a property of the
current render, not of an effect that has yet to run — the pill and the Pay
button cannot disagree inside a commit — and a lookup that lands after the
customer has retyped is filed under what was asked, so it is simply never read
back (an older answer that arrives after a newer one is dropped for the same
reason: only the latest press may report).

The question is the **whole** question: product, id, **and the sibling server
id**. G2B resolves a player _on a server_, so an id-only match is not a match.
This one is easy to miss because of how the form behaves: on MLBB the verified
id collapses into the confirmation pill while the server stays an ordinary
editable field beside it, so a buyer could verify `1313232551` on `6618`,
change the server to `7001`, and pay for a pair nobody ever checked. Nothing
downstream catches it — `orders/validation.py` checks each field alone
(presence, type, pattern, options), never the combination.

The comparison is verbatim, with no canonicalisation, and the asymmetry with
the gift flow's `currentVerdict` is deliberate: here dropping a verdict lands
on `null`, which also blocks, so an over-eager drop costs a second «Проверить»
and nothing more. There, `null` is permissive and `not_found` is the blocking
verdict, so an over-eager drop would clear the one answer that blocks a sale.

Applied on both storefronts: `apps/web` (`PurchasePanel`) and `apps/miniapp`
(`DynamicFields` + `TopUp`). The Mini App keeps the decision in a pure
`currentFieldCheck` in its own `player-check-state.ts` — its suite is node-env
with no DOM, so the gate and the review screen's nickname read one tested
function rather than two hand-written derivations.

### The `check` descriptor (`FormField.check`)

`Product.required_fields` is a jsonb list of `FormField`. One optional nested
object, `check`, opts a field into the storefront lookup — explicit opt-in on
the field, not a convention on the field's key:

```jsonc
{
  "key": "player_id",
  "label": { "ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID" },
  "type": "text",
  "pattern": "^[0-9]{6,20}$",
  "check": {
    "provider": "g2b", // which checker backs this field
    "server_field": "server", // optional: key of the sibling field supplying server_id
  },
}
```

`FieldCheck` is a `pydantic.BaseModel` (`provider: Literal["g2b", "waxpeer"]`,
`server_field: str | None = None`, `extra="forbid"`) nested on `FormField`. No
DB migration — `required_fields` is jsonb, and `admin_schemas` builds on
`FormField`, so the admin create/update API accepts `check` automatically.
Only fields carrying the descriptor render the storefront's check button.

### The endpoint

```
POST /api/v1/catalog/products/{product_id}/check-player
body:  { "player_id": "<str>", "server_id": "<str|null>" }
200:   { "status": "valid", "name": "Nickname" }
```

`status` is a three-way discriminator — `valid` (nickname resolved),
`invalid` (the supplier answered but the id does not exist — the customer's
mistake), `error` (our/supplier fault) — so the storefront can message each
case precisely and never blame the customer for an outage. (An earlier draft
returned `{valid: bool, reason}`; that collapsed "wrong id" and "our fault"
into one "couldn't check", which mis-told users to re-check a correct id.)

#### Amended 2026-09-08: a verdict we recognise, or `error`

The mapping originally read **any** unrecognised body as `invalid` — the
docstring said so in as many words: "any other body (`invalid`, empty,
unexpected) means the supplier answered but the id does not resolve". That was
wrong, and wrong in the same direction the three-way status exists to prevent,
only mirrored: it made the check a fake **rejecter**.

The failure it allowed: G2B renames the `valid` field (their client already
tolerates three different list keys on `fetch_products`, so shape drift is not
hypothetical). Every call still returns HTTP 200. No breaker fires — 200s are
successes. Nothing logs a failure. And **every player id on the platform comes
back `invalid`**, telling every customer, and from M3a every reseller, that
they mistyped. That is louder and likelier than the fake-approver case, and
`invalid` is published on `/merchant/v1` as the one answer meaning the customer
was wrong.

So both providers now require a **recognised** verdict token and answer `error`
otherwise:

- G2B: `_G2B_VERDICTS` in `player_check.py` — `valid` and `invalid`, case- and
  whitespace-tolerant. Anything else logs `player_check_unrecognised_verdict`
  and maps to `error`.
- Waxpeer: `WaxpeerClient.validate_login` **raises** `WaxpeerError` when the
  body carries no boolean `valid`, instead of `bool(body.get("valid", False))`
  reading a missing field as a refusal. Same rule `get_balance_units` already
  applied to `user.wallet`, for the same stated reason — a silently wrong
  answer is worse than a loud failure. `player_check` catches it and degrades
  to `error`, so nothing above the client changes shape.

This is a **behaviour change on the storefront**, not only on the machine API:
a customer whose check meets an unreadable supplier response now sees "couldn't
check" rather than "player not found". That is the correct message for what
happened, and the endpoint still never blocks checkout either way.
`test_player_check_service.py::test_map_g2b_response_unexpected_body_is_error_not_invalid`
replaces the test that asserted the old behaviour.

Handler logic (`yupay.modules.integrations.player_check.check_player_for_product`):

1. Load the product — as **columns**, not as an entity. `session.get(Product,
…)` fanned out to nine or more statements per check (`Product` configures
   `lazy="selectin"` for its translations, FAQs, SKU set and brand, and
   `Brand.products` is selectin in turn), which dragged the brand's whole
   product subtree through an advisory lookup. Only `required_fields` is read.
   Unknown `product_id` → **404**, carrying `code: "product_not_found"` since
   2026-09-08 so the one 4xx on this path is typed like every other on
   `/merchant/v1`. A product with no field
   carrying `check.provider == "g2b"` → **422** — this codebase maps
   `ValidationError` to 422 app-wide (`yupay.core.errors.ValidationError`),
   so the check-descriptor precondition follows the same convention as every
   other domain-validation failure. (The original spec draft called this a
   `400`; the implementation and this ADR standardise on 422 for
   consistency with the rest of the API.)
2. Resolve the G2B `game_code`: the first **active**
   `sku_supplier_mapping` among the product's SKUs with
   `supplier_slug='g2b'`, `kind='game'` → `external_product_id`. No mapping →
   `status="error"` — advisory, never an error boundary — and, since
   2026-09-08, a `player_check_no_game_mapping` warning naming the product.
   That case is the likeliest cause of a product that answers `error` forever
   (the import queue ships the form field before the mapping, or a mapping is
   deactivated during a supplier switch) and it used to log nothing at all,
   which made it indistinguishable from an unconfigured supplier.
3. Call `games_check_player(game_code, player_id, server_id, charname=None)`.
4. Map the raw response to the public `PlayerCheckOut` shape
   (`{status, name}`, dropping the internal `openid`). A 200 body whose
   `valid != "valid"` maps to `status="invalid"` (the id genuinely does not
   resolve). **Any** exception — timeout, non-2xx, malformed response — is
   folded into `status="error"`, mirroring the existing admin route. The
   endpoint never returns a 5xx for an upstream failure.

### A second provider: waxpeer (Steam login)

The Validation section below anticipated this: "Revisit if a second
checkable provider (non-G2B) ... is ever requested." It was — Steam top-ups
need the customer's Waxpeer-facing Steam login validated before checkout,
the same typo-catching problem G2B solves for numeric game player ids. The
decision held: `check_player_for_product` now resolves the field's
`check.provider` once and branches, rather than gaining a second endpoint or
a new response shape.

`provider: Literal["g2b", "waxpeer"]` on `FieldCheck` — a `waxpeer`-checked
field looks the same as the g2b example above, just
`"check": {"provider": "waxpeer"}` (no `server_field`; Steam has no
server/zone concept). For that branch, `check_player_for_product` skips game
code resolution entirely (Steam has no `game_code`/`sku_supplier_mapping` to
resolve — the login itself is the lookup key) and proxies
`WaxpeerClient.validate_login(steam_login)` instead of
`games_check_player`. The result still maps onto the same three-way
`PlayerCheckOut` contract (`valid`/`invalid`/`error`), with one difference:
`name` is always `None` — Steam has no equivalent of G2B's account nickname
resolution, so there is nothing to return on a `valid` hit. The result
caches under `playercheck:waxpeer:{login_hash}` (300 s TTL, same as g2b —
see `docs/architecture/cache-keys.md`), with `login_hash = _hash_short(steam_login)`
so the raw login is never stored or logged, mirroring the `player_id`
hashing rule below. See
`apps/api/src/yupay/modules/integrations/player_check.py` for the
implementation.

### Placement: route lives in `integrations`, not `catalog`

The route and its service live in the `integrations` module, which already
owns the G2B client and `sku_supplier_mapping`. `integrations` already
depends on `catalog` (for `Product`, `Sku`); the reverse dependency
(`catalog → integrations`) would be a cycle. The router is mounted with
`prefix="/catalog"` so the URL still reads as the storefront path
`/api/v1/catalog/products/{id}/check-player` — the URL namespace does not
have to match the owning module. `integrations/api.py` exposes the service as
`check_player_for_product(session, product_id, player_id, server_id) ->
PlayerCheckOut` for reuse.

### A third caller: the machine API (added 2026-09-08)

`POST /merchant/v1/validate/player` (Merchant B2B M3a, spec §9.1) exposes this
same service to a reseller's server, through `merchants/validate.py`. It
resolves the merchant's `sku_id` to a product, scoped to what that surface can
see (`brand.visible_b2b AND sku.visible_b2b`), and then calls
`check_player_for_product` unchanged. Nothing about the providers, the breaker
or the cache is duplicated or altered.

Two things about that surface are worth recording here, because they are
consequences of decisions made above:

- **The three-way status is what makes the endpoint safe to publish.** The
  spec's rule is "never a fake approver", and it is satisfied by the choice
  made in this ADR: folding every fault into `error` rather than into a
  cheerful `valid`. A storefront that mis-reads `error` shows a customer a
  needless warning; a reseller that mis-reads it sells a top-up into a
  stranger's account. Same discriminator, higher stakes.
- **A fourth status exists on that surface only.** The storefront answers a
  product with no checker with a `422` (`ValidationError`, per the endpoint
  section above), which is right for a UI that only ever calls it for products
  it knows are checkable. A machine caller iterating its own catalog needs
  "there is no check here" as an ordinary outcome rather than an exception, and
  needs it distinguishable from "we could not check" — one is permanent, the
  other is worth retrying. So `MerchantPlayerCheckOut.status` adds
  `unsupported`. It is a wire-contract addition on `/merchant/v1`, not a change
  to `PlayerCheckOut`, and the storefront's shape is untouched.

### §10 deviation — one synchronous external HTTP call

AGENTS.md §10 states: "No synchronous external HTTP calls in request
handlers. Always enqueue and respond with a pending status; the client
subscribes via WebSocket or polls." This endpoint deliberately violates that
rule with one in-handler call to G2B. Justification:

- **Advisory, not on the order path.** No order, payment, or fulfilment
  state depends on this call succeeding — it is pure UX feedback before
  checkout.
- **User-initiated, not automated.** The customer taps a button; there is no
  background fan-out that could turn one slow call into cascading load.
- **Short timeout, capped blast radius.** The call uses the G2B client's
  existing request timeout; a hang blocks one request, not a queue worker.
- **Redis-cached.** Repeat taps and abuse hit the cache
  (`playercheck:g2b:{game_code}:{server_id|-}:{player_id}`, 300s TTL — see
  `docs/architecture/cache-keys.md`) instead of G2B.
- **Precedent already in production.** The admin check-player route
  (`GET /admin/integrations/g2b/games/{game_code}/check-player`, ADR-0019)
  already makes this exact synchronous call; this endpoint reuses the same
  shape for a second, public caller instead of introducing a new pattern.

The machine API's `POST /merchant/v1/validate/player` (above) inherits every
one of those, with one addition: it is called by a _server_ rather than by a
person tapping a button, so "user-initiated, no fan-out" no longer holds on its
own. That is what its dedicated `merchant-validate` IP bucket is for — 120/60 s
against the prefix's 600, because it is the only endpoint on that surface that
spends a supplier's quota rather than ours.

### Positive consequences

- Customers catch a wrong player id before paying, cutting misdelivered
  top-ups without adding any new checkout dependency.
- One shared endpoint serves both miniapp (`DynamicFields`) and web
  (`PurchasePanel`).
- No schema migration, no admin UI work — `check` passes through the
  existing jsonb form schema and admin API untouched.

### Negative consequences

- A second synchronous external call site in the codebase alongside the
  admin route — anyone auditing §10 compliance must know both are
  intentional, not drift. Both are now cross-referenced to this ADR.
- Per-IP rate limiting (`guard_ip`, bucket `check_player`) is required to
  blunt id-enumeration abuse; a misconfigured or removed limiter would
  reopen that surface.

## Validation

`apps/api/tests/integration/test_player_check_endpoint.py` (and the
`integrations` service unit tests) cover: game_code resolution happy path and
no-mapping → `unavailable`; response mapping for valid/invalid/exception
cases via respx (no real HTTP); not-checkable product → 422; unknown product
→ 404; rate-limit 429; `player_id` absent from emitted logs (hash only, via
the G2B module's existing redaction helper). The same suite now also covers
the waxpeer branch (see "A second provider: waxpeer" above): valid/invalid/
error mapping via respx, `product_is_checkable` recognising a
`waxpeer`-only field, and the Steam login absent from emitted logs (hash
only) — the second-checkable-provider case this section used to flag as a
"revisit" trigger has happened and slotted into the existing three-way
contract without a schema or endpoint change, confirming the extensibility
bet this ADR made. Still open: a `charname` pre-purchase check is not
implemented — the `check` descriptor's `provider` field remains
`Literal`-extensible for that if it's ever requested.

## Alternatives considered (detail)

### Option 2 — async job + poll/WebSocket

Would keep the request handler free of external I/O, matching §10 to the
letter. Rejected because the lookup already completes in about a second and
the UI need is synchronous ("tap → see nickname"); wrapping it in a job with
a status channel adds a queue hop, a WebSocket subscription (or poll loop),
and idempotency-key bookkeeping for a call whose failure mode is already
fully contained (advisory, cached, rate-limited).

### Option 3 — gate checkout on a valid check

Would give the strongest typo protection but makes G2B availability a
checkout dependency, contradicting the resilience goal that motivated
keeping payments/fulfilment decoupled from suppliers elsewhere in the
codebase (ADR-0013, ADR-0019). Rejected outright during brainstorming.

## Which games may carry the check (verified 2026-08-16, `freefire_cis` re-verified 2026-08-20)

Not every G2B title has a validator behind `checkPlayerId`, and the ones that
do not **do not say so** — they answer `{"valid": "valid"}` to anything. Probed
each mapped game with an id that cannot exist (`999999999999`):

| game code                      | bogus id answers | verdict                                                           |
| ------------------------------ | ---------------- | ----------------------------------------------------------------- |
| `pubgm`                        | `invalid`        | real validator                                                    |
| `mlbb` / `mlbb_ru`             | `invalid`        | real validator                                                    |
| `magic_chess_gogo` / `mcgg_ru` | `invalid`        | real validator                                                    |
| `arena_breakout`(+`_infinite`) | `invalid`        | real validator                                                    |
| `deltaforce`                   | `invalid`        | real validator                                                    |
| `bloodstrike`                  | `invalid`        | real validator                                                    |
| `whiteout_survival`            | `invalid`        | real validator                                                    |
| `freefire_cis`                 | `invalid`        | real validator (since 2026-08-20 — was a rubber stamp, see below) |
| `genshin`                      | **`valid`**      | **rubber stamp — no check**                                       |
| `honkai_star_rail`             | **`valid`**      | **rubber stamp — no check**                                       |

A rubber-stamping game must never carry `check`. The point of this feature is
to catch a typo before money moves; a green "account confirmed" pill printed
over any typo does the opposite — it manufactures confidence exactly where the
customer would otherwise hesitate. Absence of a check is the honest state
there, and the storefront degrades to what it did before the feature existed.

`/games/fields` does **not** answer this question: `genshin` and
`honkai_star_rail` both declare `["userid", "serverid"]` like the games that do
validate. Only calling the validator distinguishes them. Re-run the probe
before enabling `check` on any new game.

**Free Fire was a per-title gap, not a per-game one — now closed.** G2B sells
ten regional Free Fire titles; nine always validated properly (`freefire_bd`,
`_br`, `_latam`, `_sgmy`, `_vn`, `_global`, `_sg`, `_me`, `_tw` all answer
`invalid` to a bogus id). Only `freefire_cis` — the one we sell — rubber-
stamped, and it was also the only one whose `/games/fields` returned
`404 game fields not available`, pointing at a hole on G2B's side specific to
the CIS title rather than a deliberate "this game cannot be checked". Re-probed
2026-08-20 after the supplier reported it now validates: `freefire_cis`
answers `invalid` to the bogus id like every other checkable title, so `check`
was enabled on `free-fire-*` in `seed_catalog.py`, with
`scripts/seed/2026-08-20_enable_free_fire_player_check.sql` applying the same
change to rows already seeded on prod/staging (same pattern as
`scripts/seed/2026-08-16_enable_player_check.sql`).

## References

- `docs/superpowers/specs/2026-07-16-storefront-player-check-design.md` — feature design spec
- [ADR-0019](./0019-g2b-integration.md) — G2B integration, admin check-player precedent
- [ADR-0009](./0009-catalog-three-level-plus-form-schema.md) — `required_fields` form schema
- [ADR-0028](./0028-fastapi-rate-limiting.md) — rate-limiting infrastructure (`guard_ip` / slowapi)
- `docs/architecture/cache-keys.md` — `playercheck:g2b:{game_code}:{server_id|-}:{player_id}`,
  `playercheck:waxpeer:{login_hash}`
- `apps/api/src/yupay/modules/integrations/player_check.py` — service implementation
- `apps/api/src/yupay/modules/integrations/routes.py` — public + admin routes
- `apps/api/src/yupay/modules/catalog/schemas.py` — `FieldCheck` / `FormField`
