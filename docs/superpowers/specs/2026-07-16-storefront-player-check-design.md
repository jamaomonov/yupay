# Storefront player-id check (G2B nickname lookup)

- **Date**: 2026-07-16
- **Status**: Approved, ready for implementation
- **Surfaces**: miniapp + web storefront, API

## Problem

For game top-ups (PUBG Mobile, Mobile Legends, …) the customer types a numeric
player id at checkout. A typo means the top-up is delivered to a stranger's
account and is effectively unrecoverable. G2B exposes a `checkPlayerId` call that
returns the account's nickname for a given id, and YuPay already wraps it
(`games_check_player` in the G2B client) and uses it in an **admin-only**
diagnostic route. Customers have no way to reach it.

Goal: let the customer enter their id, tap **Проверить**, and see the nickname
that id resolves to — so they catch a wrong id before paying.

## Decisions (settled during brainstorming)

1. **Advisory, not gating.** Seeing the nickname is a convenience. The purchase is
   never blocked by the check — if G2B is down or the game has no checker, the
   customer can still order. This keeps checkout resilient to an external
   dependency.
2. **Explicit opt-in on the form field**, not convention on the field key. A field
   carries a `check` descriptor; only a field that has it shows the button.
3. **Both surfaces** (miniapp `DynamicFields`, web `PurchasePanel`) get the button
   in this iteration, over one shared endpoint.

## Non-goals

- No gating / mandatory verification.
- No admin UI toggle for the `check` descriptor — the field is JSON-editable and
  the admin API passes the new property through. A dedicated editor control is a
  possible follow-up.
- No `charname` support in the pre-purchase check (rare; the check is a _lookup_,
  the customer does not have a charname to supply). It remains supported at
  fulfilment, unchanged.

## Design

### A. Form-schema extension (`FormField`)

`Product.required_fields` is a jsonb list of `FormField`. Add one optional nested
object, `check`, to the field the customer verifies (the player-id field):

```jsonc
{
  "key": "player_id",
  "label": { "ru": "ID игрока", "en": "Player ID", "uz": "Oʻyinchi ID" },
  "type": "text",
  "pattern": "^[0-9]{6,15}$",
  "check": {
    "provider": "g2b", // which checker backs this field
    "server_field": "server", // optional: key of the sibling field that supplies server_id
  },
}
```

- All check configuration lives on one field and references the server field by
  key, so the descriptor is self-contained and extensible (future providers, a
  future `charname_field`).
- Pydantic model: a `FieldCheck` submodel with `provider: Literal["g2b"]` and
  `server_field: str | None = None`; `FormField.check: FieldCheck | None = None`.
  `extra="forbid"` is preserved.
- No DB migration — `required_fields` is jsonb. `admin_schemas` builds on
  `FormField`, so the admin create/update API accepts `check` automatically.

### B. Public endpoint

```
POST /api/v1/catalog/products/{product_id}/check-player
body:  { "player_id": "<str>", "server_id": "<str|null>" }
200:   { "valid": true, "name": "Nickname", "reason": null }
```

Handler logic:

1. Load the product; find the field whose `check.provider == "g2b"`. If none →
   `400` "product is not checkable" (a client bug — the button should only render
   when the field is present). Unknown `product_id` → `404`.
2. Resolve the G2B `game_code`: the first **active** `sku_supplier_mapping` among
   the product's SKUs with `supplier_slug='g2b'`, `kind='game'` →
   `external_product_id`. A product's game SKUs share one game_code; the resolver
   asserts/uses the first and is covered by a test. If no g2b game mapping →
   `{valid:false, reason:"unavailable"}` (advisory; never an error boundary).
3. Call `games_check_player(game_code, player_id, server_id, charname=None)`.
4. Map the raw response to `CheckPlayerOut` public shape `{valid, name, reason}`
   (drop `openid` — internal). Any exception is folded into
   `{valid:false, reason:<short>}`, mirroring the existing admin route.

Placement & boundaries:

- The route and its service live in the **integrations** module, which already
  owns the G2B client and the `sku_supplier_mapping`. A public (no `require_admin`)
  router is added there and mounted so the URL reads as the storefront path
  `/api/v1/catalog/products/{id}/check-player`. Defining it in integrations avoids
  a `catalog → integrations` dependency edge (integrations already depends on
  catalog; the reverse would be a cycle). The URL namespace does not have to match
  the owning module.
- Exposed to the rest of the app through the integrations public interface
  (`integrations/api.py`) as `check_player_for_product(session, product_id,
player_id, server_id) -> CheckPlayerOut`.

Constraints (project rules):

- **Rate limit (§9).** Public + anonymous (a guest may check before logging in).
  slowapi per-IP limit via the existing `_client_ip` key func — a tight bucket
  (target ~20/min) to blunt id-enumeration abuse. An integration test asserts the 429.
- **PII (§9).** `player_id` is never logged in plaintext; reuse the G2B module's
  existing short-hash helper for any log line. `player_id` / nickname are not
  persisted by this endpoint — it is a transient lookup.
- **Redis cache.** Cache `(game_code, player_id, server_id) → result` for a short
  TTL (5 min) to cut repeat G2B calls (customers tap twice) and soften abuse. Key
  documented in `docs/architecture/cache-keys.md`.
- **§10 deviation — synchronous external call.** §10 forbids synchronous external
  HTTP in request handlers. This endpoint deliberately makes one: the UX is
  "tap → nickname in ~1s", the call is advisory, user-initiated, off the automated
  order path, short-timeout, and cached. The admin check-player route already
  establishes this synchronous pattern. Recorded in an ADR.

### C. Frontend (miniapp + web)

- Extend the shared `FormField` TS type in `apps/miniapp/src/lib/catalog.ts` and
  `apps/web/src/lib/catalog.ts` with the optional `check` object (regenerated
  `packages/api-client` types carry it from OpenAPI; the hand-typed `catalog.ts`
  mirrors it).
- **miniapp** — `DynamicFields.tsx`: for the field carrying `check`, render a
  **Проверить** button inside/under the input. On tap: read `player_id` from this
  field and, if `check.server_field` is set, the server value from that sibling
  field; call the endpoint. States: idle → loading → success (green ✓ + nickname)
  → soft failure (muted `reason`, no error boundary). Disabled until the field
  matches its `pattern` / is non-empty. Re-checks reset on value change.
- **web** — `PurchasePanel.tsx`: same behaviour in the web form renderer.
- **i18n**: new keys (`field.check`, `field.checking`, `field.checkOk`,
  `field.checkFailed`, …) added to ru/en/uz in the same PR.

### D. Seed / admin

- `seed_catalog.py`: `_player_id_field()` gains an optional `check=` param;
  game products (PUBG Mobile, etc.) seed the descriptor. Non-game products
  unaffected.
- Admin: no code change required for the API to accept `check` (schema
  pass-through). UI editor control is out of scope (see non-goals).

## Data flow

```
customer types id ──▶ [Проверить] ──▶ POST /catalog/products/{id}/check-player
                                            │
                        resolve field.check + game_code (sku_supplier_mapping)
                                            │
                         Redis cache hit? ──yes──▶ return cached {valid,name}
                                            │no
                          games_check_player(game_code, id, server_id)
                                            │
                        map → {valid,name,reason}, cache, return
                                            │
                          UI shows nickname (✓) or reason (muted)
```

Fulfilment is unchanged: the same `player_id` / `server` field values still land
in `order_item.fulfillment_data` and drive the G2B order as today.

## Testing

- **Backend (integrations, adapter-grade ≥95%)**:
  - game_code resolution from `sku_supplier_mapping` (happy path; no-mapping →
    `unavailable`).
  - response mapping: valid → `{valid:true, name}`; invalid → `{valid:false,
reason}`; G2B exception → `{valid:false, reason}` (respx-mocked, no real HTTP).
  - not-checkable product → 4xx.
  - rate-limit 429.
  - PII: assert `player_id` absent from emitted logs (hash only).
- **Frontend**: `DynamicFields` / `PurchasePanel` component tests for the button's
  loading / success / failure states and the disabled-until-valid rule.

## Docs

- New ADR: public storefront player-check endpoint + the §10 synchronous-call
  deviation and its justification.
- `apps/api/src/yupay/modules/catalog/README.md`: document the `check` descriptor
  in the form-schema section.
- `docs/architecture/cache-keys.md`: the player-check cache key + TTL.
- Regenerate `docs/api/openapi.json` + `packages/api-client` (`make gen-api`).
- Update ru/en/uz catalogs.

## Open questions

None — all resolved during brainstorming (advisory; explicit `check` descriptor;
both surfaces; sync-with-cache; route in integrations).
