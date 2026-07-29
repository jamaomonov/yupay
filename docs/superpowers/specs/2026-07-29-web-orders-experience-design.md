# Web order experience — design spec

**Date:** 2026-07-29
**Status:** approved (design), pending phase plans
**Surfaces:** `apps/web` (primary), `apps/miniapp` (parity), `apps/api` (backend). Built in **3 phases (1 → 2 → 3)**.

## Problem

The web order-details experience is poor and leaks internal data:

1. **Security leak.** `GET /orders/{id}/deliveries` strips only the single key `external_id` (a blocklist, `fulfillment/routes.py:90`). Real fulfilments send the customer the **internal supplier `source`** (`waxpeer`/`g2b`/`inventory`) plus `external_order_id`, `external_product_id`, `catalogue_name`, `inventory_code_id`, `sku_id`, raw `amount_units`/`give_amount_units`. `OrderItemOut.supplier_order_id` also leaks an internal supplier order id on every order. The web `ArtifactReveal` and the Mini App `ArtifactBlock` JSON fallback render these verbatim (screenshot: `SOURCE: waxpeer`).
2. **Thin, untranslated details page.** Web `OrderStatus.tsx` shows only the status heading + a raw artifact dump + a review CTA. No order total, no provider, no items, no dates. A `fulfilling` (выполняется) order shows nothing but the word. Artifact labels are raw English (`humanizeKey`), money is raw (`20000`).
3. **Missing data.** Neither web nor Mini App shows the **payment provider** the customer paid with. Web account list shows `total_usd` (USD) instead of `total_charged` (what they actually paid).
4. **Post-payment dead end.** After paying at the acquirer, the customer isn't returned to their order.
5. **No guest order history.** Guests can reach only one order at a time via the emailed link; there's no list and no way to carry guest orders into an account after signup.

## Decisions (from the user)

- **Post-payment → the order page** (`/orders/{id}`, which already live-updates via poll/WS + fires the delivered modal).
- **Guest→account claim by verified-email match** — claim only orders whose `guest_email` equals the account's **verified** email. **Blocker to resolve in Phase 3:** signup currently emails a verification link but lets the user in without verifying, so "verified email" isn't yet enforced/trustworthy — Phase 3 must make email-verification real (enforce it and/or track a trustworthy `email_verified` flag) before the claim can rely on it.
- **Delivered artifact = deliverable + human receipt** — show the code/key/voucher and the account login the customer themselves entered, plus a human "credited X" line derived from the order (denomination), never raw `amount_units`.
- **Phased 1 → 2 → 3.**

---

## Phase 1 — Security fix (ship first, standalone)

**Goal:** internal/supplier data can no longer reach any frontend.

- Replace the artifact blocklist with an explicit **whitelist** in `_to_customer_delivery_out` (`apps/api/src/yupay/modules/fulfillment/routes.py:93-108`). Customer-safe keys ONLY:
  `code`, `codes`, `key`, `pin`, `serial`, `steam_login` (and any explicitly-safe login/account the customer supplied), `message`, `fulfillment_data` (the customer's own checkout input). Every other key is dropped before serialization — in particular `source`, `external_order_id`, `external_product_id`, `catalogue_name`, `inventory_code_id`, `sku_id`, `amount_units`, `give_amount_units`, `external_id`.
  Rationale: a whitelist is the only robust fix — a blocklist re-leaks the moment a new supplier adds a field.
- Remove `supplier_order_id` from the **customer** `OrderItemOut` (keep it on `OrderAdminOut`/admin only). It's an internal supplier order id currently sent to every customer (`orders/schemas.py:71-83`).
- Add a backend test asserting a waxpeer-style artifact (`source`, `external_order_id`, …) is fully stripped to the whitelist on `GET /orders/{id}/deliveries`, and that `OrderItemOut` no longer carries `supplier_order_id`.
- Frontends need no change to be safe (the data is gone at the API), but the web `ArtifactReveal` and Mini App `ArtifactBlock` JSON fallback should stop dumping unknown keys anyway — folded into Phase 2's rework.

**Deliverable:** the leak is closed at the API for both surfaces; deployable on its own.

---

## Phase 2 — Order-details rework + payment provider + money

**Backend**

- Add the **paid provider** to the customer `OrderOut`: `payment_provider: str | None` = the `provider` of the order's succeeded `Payment` (values `click`/`click_miniapp`/`payme`/`uzum`/`octo`/`wallet`/…; normalise `click_miniapp` → `click`). Resolved in `get_order_for_actor`/assembly with one query, no N+1. (Alternative considered: a separate `/payments/by-order/{id}` call — rejected; one field on OrderOut is simpler for both surfaces.)
- Regenerate `docs/api/openapi.json`.

**Web (`OrderStatus.tsx` + order page)** — full rework into a clear layout:

- **Status block** with per-status content, including a real `fulfilling` state ("оплата принята, выдаём — обычно автоматически; поддержка на связи"), not just the word.
- **Order summary:** the **total paid** (`total_charged` + `currency`, formatted; USD as `$X.XX`, UZS whole with grouping — reuse a shared money formatter), the **payment provider** (logo or localized name via a shared provider→{name,logo} map), **created/paid/delivered dates**.
- **Items:** brand · what was bought (denomination/region from `display`) · qty. (1 order = 1 item today, but render the list.)
- **Delivered artifact:** a clean, translated reveal of ONLY the whitelisted fields — the deliverable (`code`/`key`, copyable) and the customer's login — plus a human "credited"/"delivered" confirmation derived from the order's denomination, never raw units. No raw key dump.
- Fix the account orders list to show `total_charged` + `currency` (what they paid), consistent with the detail page.
- **i18n:** add the order-detail keys to `packages/i18n/locales/{ru,en,uz}/web.json` (`orders.*`): total, paidWith/provider, item, delivered-code, receipt lines, per-status body copy. All three locales.

**Mini App parity**

- Add the **payment provider** display to the order view (same OrderOut field + provider map).
- The Mini App artifact surfaces are already safe after Phase 1 (nothing sensitive arrives); tidy the `ArtifactBlock` fallback so it never dumps raw JSON.

**Shared:** a provider→{displayName, logoAsset} mapping (icons already exist under `apps/web/public/` for the checkout selector — reuse/relocate to a shared spot for order display).

**Verification:** each visible web fix is confirmed via Playwright against the running dev app (per the user's requirement) — status/fulfilling content, total, provider, translated safe artifact.

---

## Phase 3 — Post-payment flow + guest orders + verified email

**Post-payment → order page**

- Set the payment intent's acquirer **return_url** to the order page (`/orders/{id}?email=<guest>` for a guest, `/orders/{id}` for a user), so after paying the customer lands on their live order. Trace where the intent's return/redirect URL is configured (payments gateways / `POST /payments/intents`) and point it at the order page. The order page already polls/WS to delivered and fires the delivered modal.

**Guest orders (localStorage list)**

- After a guest checkout, persist `{ orderId, email, brandSlug, brandName, createdAt }` to `localStorage` (`yupay.guest_orders`), append-only, capped/deduped.
- A guest-visible **orders page** lists these entries and links each to `/orders/{id}?email=` (the existing guest-access mechanism). The current account list redirects guests to login — instead, for a guest it renders the localStorage list.

**Claim on login (verified-email match)**

- Backend `POST /orders/claim`: for the authenticated user, reassign every guest order whose `guest_email == user.email` **and** the user's email is **verified** — set `user_id`, null `guest_email` (respecting the `user_id` XOR `guest_email` constraint and the `reviews.order_id` FK). Idempotent; returns the claimed count.
- Client: on successful login/signup, call the claim endpoint, then clear the matching `localStorage` guest entries.
- **Email-verification blocker (must be resolved here):** today signup sends a verification link but admits the user unverified, so `user.email` isn't a trustworthy claim key. Phase-3 planning must decide + implement the fix — options to weigh at plan time: (a) enforce verification before login/claim, (b) add/trust an `email_verified` flag and gate the claim on it (unverified users simply can't claim until they verify). The claim MUST NOT reassign orders to an unverified email.

**Verification:** the post-payment redirect, the guest list, and the claim-on-login are each confirmed via Playwright (guest checkout → order page → guest list → login → orders migrated).

---

## Out of scope / non-goals

- Redesigning checkout itself (only its post-payment redirect).
- Multi-item carts (still 1 order = 1 item).
- Changing the delivered-modal or the reviews feature (they stay; the order page keeps firing the modal + the rate CTA).
- Refunds/partial-refund UI.

## Cross-cutting constraints

- Money: `Decimal` full-units in the DB; format per currency (UZS/RUB 0-dec, USD/USDT 2-dec) with locale grouping — never raw.
- Never send supplier/internal identifiers to any frontend (Phase 1 whitelist is the guarantee).
- i18n: every new user-facing string in ru/en/uz in the same change.
- `mypy --strict`/ruff (api), `tsc` strict/eslint/prettier (web+miniapp). Do NOT run a host `next build` for web (bind-mount `.next` trap) — typecheck + Playwright suffice locally; CI builds.
