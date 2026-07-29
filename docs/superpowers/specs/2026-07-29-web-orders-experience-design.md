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

## Phase 3 — Post-payment flow + guest orders + enforced email verification

**Decision (locked):** email verification is **enforced at password login**. This is the strict option; the design below neutralizes its two footguns (existing-user lockout, prod email dependency).

**Email verification enforcement**

- `User.email_verified_at` already exists (nullable; `NULL` = unverified) and the verify-email endpoint already sets it. Login just never checks it — that's the gap.
- **Password login** (`login_password`) rejects a user with `email_verified_at IS NULL` → a distinct `email_unverified` error (HTTP 403) the web can detect to show a "verify your email" state + resend button. **Telegram login is exempt** (no email; those users are authenticated by Telegram — set their `email_verified_at` at creation or bypass the check on that path).
- **Register** no longer issues a session immediately: it creates the account, sends the verify email, and returns a "verification required" response (no tokens). The web shows "проверьте почту". **Verify-email** endpoint, on success, sets `email_verified_at` **and issues a session** (auto-login) so the link flow ends logged-in and triggers the claim.
- **Resend**: new `POST /auth/resend-verification` (rate-limited) so a user who lost/never got the email can re-trigger; wired to the "verify your email" screen + the login-blocked error.
- **Grandfather existing users**: a data migration sets `email_verified_at = now()` for all existing users where it is `NULL`, so enforcement applies only to new signups and no current account is locked out.
- **Operational note (runbook)**: with login gated on verification, prod email delivery (Resend/Postmark) becomes load-bearing — a signup can't complete without a working mailer. Add a runbook note; keep the resend path as the recovery.

**Post-payment → order page**

- Web `PurchasePanel` sends `return_url = ${origin}/{locale}/orders/{id}[?email=<guest>]` in the payment-intent body so the acquirer returns the customer to their live order. Backend default return_url is derived from `settings.web_base_url` (replacing the hardcoded `app.yupay.uz/checkout/return`; octo's `telegram_miniapp_url` default likewise), and the backend validates a client-supplied `return_url` is same-origin as `web_base_url` (open-redirect hardening). The order page already polls/WS to delivered and fires the delivered modal.

**Guest order viewing (pre-existing gap this phase must fix)**

- The web order page currently sends only `X-Guest-Email`, not a `Guest` token, so a cold guest link 401s. The order page, for a guest (email present, no user), mints a `Guest` token from the email (`mintGuestToken`, freely mintable) and sends `Authorization: Guest <token>` + `X-Guest-Email` on the order + deliveries fetches. This makes both the emailed single-order link and the new guest list actually load.

**Guest orders (localStorage list)**

- After a guest checkout, `PurchasePanel.pay()` persists `{ orderId, email, brandSlug, brandName, createdAt }` to `localStorage` (`yupay.web.guest_orders`), append-only, capped/deduped — saved before the acquirer redirect and on the mock path.
- A guest-visible **orders page**: `account/orders` currently bounces guests to login; instead, for a guest (no user) it renders the localStorage list, linking each entry to `/orders/{id}?email=`.

**Claim on login (verified-email match)**

- Backend `POST /orders/claim` (authenticated): reassign every guest order where `guest_email == user.email` **and** `user_id IS NULL` **and** the user's `email_verified_at IS NOT NULL` — set `user_id`, null `guest_email` in one UPDATE (satisfying the `user_id` XOR `guest_email` CHECK). The `reviews.order_id` FK targets the unchanged `orders.id` PK, so it's unaffected. Idempotent; returns the claimed count. (With login now gated on verification, the caller is always verified; the `email_verified_at` gate is belt-and-suspenders.)
- Client: in the single post-auth funnel (`auth.tsx afterTokens`) and on verify-email success, call the claim endpoint, then clear the matching `localStorage` guest entries.

**Verification:** the post-payment redirect, the guest single-order link + list loading (guest-token auth), the enforced-login/verify/resend flow, and the claim-on-login are each confirmed via Playwright (guest checkout → order page → guest list → register → verify → orders migrated).

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
