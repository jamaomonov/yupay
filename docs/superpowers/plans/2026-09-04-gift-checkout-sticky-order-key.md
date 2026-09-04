# Gift Checkout — Sticky Order Key (no duplicate orders on retry)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Branch: `main` (Steam Gifts is LIVE on prod).

**Goal:** A buyer who retries after a failed payment (typically "insufficient wallet balance") resumes the SAME order instead of creating a second one.

**Architecture:** No backend work. `create_order` already replays by `Idempotency-Key` — `_existing_idempotent_order` is checked up-front (`apps/api/src/yupay/modules/orders/service.py:698`) and returns the existing order untouched. The gap is purely that both gift panels mint a fresh `crypto.randomUUID()` on every buy click. Fix: the panel keeps the key sticky for as long as the _order contents_ are unchanged, and mints a new one when they change, after a success, or when the replayed order is no longer payable.

**Tech Stack:** Next.js 15 + TanStack Query (web), Vite + React 19 + wouter (miniapp).

**Spec:** none — this closes the item parked during the wallet review (2026-09-03): "buyGift creates the order BEFORE the intents call, so a race-409 leaves an orphaned unpaid order and a retry mints a second one."

## Global Constraints

- **Backend untouched.** No Python in either task's diff.
- **Correct-by-construction key reset.** Store the key together with a _fingerprint_ of exactly the fields that determine the order body, and mint a new key whenever the fingerprint differs. Never scatter manual `resetKey()` calls around input handlers — a forgotten one is a money bug.
- **The fingerprint covers order contents only**, never the payment method: `sku_id`, `qty`, `amount_usd`, and every `fulfillment_data` field (`app_id`, `package_id`, `region`, `invite_url`), plus the delivery email where the surface has one. Switching provider (card ↔ wallet) MUST keep the same key — it is the same order.
- **Over-resetting is safe, under-resetting is not.** Replaying a key returns the ORIGINAL order with its original price and contents; if the buyer changed region/edition/recipient and we reuse the key, they would be charged for the old selection. When in doubt, mint a new key — that is exactly today's behaviour.
- **Stale-order recovery.** `ORDER_EXPIRY_SECONDS = 10 * 60`, and `create_intent` raises `ConflictError("order is not awaiting payment", extra={"status": …})` for an order that is no longer `pending_payment`. So a retry more than ~10 minutes later would replay an `expired` order and 409 on the intent. Handle it: when the intents call fails with that shape, mint a fresh key and retry the whole flow **once**, automatically. Match by structure (`extra.status` present / the order-not-awaiting-payment conflict), never by message text.
- The key must also be dropped after a **successful** purchase, so the next purchase is a new order.
- TS strict, no `any`, no uncommented `as`. Money stays strings.
- Conventional Commits; do NOT push, do NOT deploy. Never stage the pre-existing dirty files (`Makefile`, `scripts/seed.py`, `scripts/seed/2026-08-21_telegram_stars_unit_sku.py`).
- **Out of scope** (documented follow-up, do not touch): web `apps/web/src/components/store/PurchasePanel.tsx` and miniapp `apps/miniapp/src/pages/TopUp.tsx`. They share the same gap, but their carts carry promo codes, quantities and variable amounts, so their fingerprint is materially harder to get right and deserves its own pass.

---

### Task S1: Web — sticky order key in the gift panel

**Files:**

- Modify: `apps/web/src/lib/gift-checkout.ts` (accept the key + surface the not-payable conflict)
- Modify: `apps/web/src/components/gifts/GiftPurchasePanel.tsx` (own the key)
- Test: `apps/web/src/components/gifts/GiftPurchasePanel.test.tsx`

**Current behaviour to change:** `buyGift` generates the order `Idempotency-Key` internally (`crypto.randomUUID()`), so every call is a new order. Move key ownership to the caller: `buyGift({..., idempotencyKey})`. Keep the _payment_ intent's own key generated per attempt — retrying the intent for the same order is already "create or reuse" server-side.

**Produces (used by the tests):** an exported pure helper for the fingerprint, e.g. `orderFingerprint(input): string`, so the reset rule is unit-testable without rendering.

**Behaviour:**

- The panel holds `{fingerprint, key}` (a ref or state). On buy: recompute the fingerprint; if it differs from the stored one, mint a new key and store both.
- On success: clear the stored pair.
- On an intents conflict indicating the order is no longer awaiting payment: mint a fresh key, store it, and re-run the purchase once. If that second attempt also fails, surface the error normally — never loop.
- Everything else about the flow is unchanged.

**Steps:** tests first — (a) two consecutive failed attempts with unchanged inputs send the SAME order `Idempotency-Key`; (b) changing the region (or edition/invite) between attempts sends a DIFFERENT key; (c) switching the payment method between attempts keeps the SAME key; (d) a success clears the key so the next purchase differs; (e) an "order is not awaiting payment" conflict triggers exactly one automatic retry with a fresh key. Run to fail → implement → pass → `pnpm --filter @yupay/web test -- --run`, `tsc --noEmit`, lint, locale parity. NEVER run `next build` on the host. Commit `fix(web): resume the same gift order when a payment retry follows a failure`.

---

### Task S2: Miniapp — sticky order key in the gift panel

**Files:**

- Modify: `apps/miniapp/src/lib/orders.ts` (`performCheckout`/`CreateOrderInput` accept an optional caller-supplied order key; default stays today's generated one so `TopUp` is untouched)
- Modify: `apps/miniapp/src/pages/GiftGame.tsx` (own the key)
- Test: `apps/miniapp/src/pages/GiftGame.test.tsx`, `apps/miniapp/src/lib/orders.test.ts`

**Behaviour:** identical to S1. `performCheckout` currently calls `newIdempotencyKey("order")` internally (`apps/miniapp/src/lib/orders.ts`); add an optional `orderIdempotencyKey` to its input and fall back to the generated one when absent, so `TopUp`'s call site keeps working byte-identically.

**This app's test convention is strict:** node env, NO jsdom, NO React Testing Library. So the fingerprint helper and the "should I mint a new key?" decision must be exported pure functions, tested directly — mirror how `walletPayState`, `walletSubmitReady` and `nextSelectedMethodId` are already tested in `GiftGame.test.tsx`. Cover the same five cases as S1 at the helper level, plus an `orders.test.ts` case proving `performCheckout` forwards a supplied key verbatim and still generates one when omitted.

**Steps:** tests first → fail → implement → pass → `pnpm --filter @yupay/miniapp test -- --run`, typecheck, lint, locale parity, and confirm `TopUp`'s tests stay green. Commit `fix(miniapp): resume the same gift order when a payment retry follows a failure`.
