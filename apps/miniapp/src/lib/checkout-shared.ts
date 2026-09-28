/**
 * Checkout helpers shared by the mini app's buy pages (Steam Gifts, CS2 skins):
 * the pay-from-balance tile state, the method re-selection once provider status
 * loads, and the "order no longer awaiting payment" 409. Moved out of
 * `pages/GiftGame.tsx` so another page can use them without pulling that page
 * into its chunk; `GiftGame` re-exports them for its own tests.
 */

import { ApiError } from "./api";
import { translate } from "./i18n/core";
import { methodVisibility, type MethodVisibility, type ProviderAvailability } from "./orders";
import { PROVIDER_BY_METHOD } from "./payment-methods";

/** The pay-from-balance option — checkout-only, not an acquirer. */
export const WALLET_METHOD_ID = "wallet";

/** The acquirer map plus the wallet, for resolution/availability. */
export const PROVIDER_BY_METHOD_FULL: Record<string, string> = {
  ...PROVIDER_BY_METHOD,
  [WALLET_METHOD_ID]: "wallet",
};

/** What the wallet ("pay from balance") tile should say and whether it's
 *  selectable — mirrors `TopUp.tsx`'s inline `walletEnough`/`walletShortfall`/
 *  `disabled` math exactly (see `WalletPayOption.tsx`), pulled out as a pure
 *  function so it's unit-testable under this app's node-env convention
 *  instead of only reachable by rendering. */
export interface WalletPayState {
  /** Whether the balance is known to cover `total`. Optimistically `true`
   *  while the balance is still loading (`balance === null`) — a submit
   *  re-checks server-side regardless, same belt-and-suspenders posture as
   *  `TopUp`. */
  enough: boolean;
  /** Non-selectable: an admin has the wallet in maintenance, the total
   *  isn't known yet (FX-unavailable `price_uzs`), or the balance is short
   *  and no longer loading. */
  disabled: boolean;
  /** UZS still needed to afford `total`. `0` unless genuinely short. */
  shortfall: number;
  /** `true` when there is nothing to weigh the balance against — the
   *  selected line's `price_uzs` was `null` (FX unavailable). Distinct from
   *  an insufficient balance: never compare against a guessed total. */
  unknownTotal: boolean;
}

export function walletPayState({
  balance,
  total,
  loading,
  visibility,
}: {
  balance: number | null;
  total: number | null;
  loading: boolean;
  visibility: MethodVisibility;
}): WalletPayState {
  if (total === null) {
    return { enough: false, disabled: true, shortfall: 0, unknownTotal: true };
  }
  const enough = balance === null ? true : balance >= total;
  const shortfall = balance === null || enough ? 0 : total - balance;
  const disabled = visibility === "maintenance" || (!loading && !enough);
  return { enough, disabled, shortfall, unknownTotal: false };
}

/**
 * Whether Buy may actually be submitted for the currently selected method —
 * the honest twin of `walletPayState.enough`'s optimistic display value.
 * Every non-wallet method is always ready (the acquirer path is untouched
 * by any of this). For the wallet, "ready" requires a balance that has
 * actually resolved (`balance !== null` — a still-loading balance is not a
 * known-sufficient one) AND a known total (`total !== null` — FX
 * unavailable must never be guessed past) AND that balance covering that
 * total. Pulled out as a pure function so this live-payment gate is
 * unit-tested directly rather than only reachable by rendering. Mirrors the
 * web panel, which only enables Buy once its wallet tile reaches the
 * genuine `"ready"` state (`canPayFromBalance(walletState)`), never a
 * loading or unknown one.
 */
export function walletSubmitReady({
  methodId,
  balance,
  total,
}: {
  methodId: string;
  balance: number | null;
  total: number | null;
}): boolean {
  if (methodId !== WALLET_METHOD_ID) return true;
  return balance !== null && total !== null && balance >= total;
}

/**
 * Decide the next selected method id when live provider status changes —
 * the reselect effect's own logic, pulled out pure so the wallet-stickiness
 * rule is unit-tested directly instead of only reachable by mounting the
 * page. `statusBySlug === null` (not yet loaded) leaves `current` alone,
 * same fail-open posture as `methodVisibility`. A wallet selection is NEVER
 * reassigned here, regardless of its own live status — its tile and
 * `walletSubmitReady`/`canBuy` are what decide whether it's usable, not
 * this reselection; reassigning it would silently swap the buyer onto a
 * card with no notice (mirrors `GiftPurchasePanel.tsx`'s identical guard on
 * web: `if (current === WALLET_METHOD_ID) return current;`). Otherwise:
 * keep `current` if it still resolves to an `"active"` provider, else fall
 * back to the first acquirer that does, else deselect entirely (`""`).
 */
export function nextSelectedMethodId({
  current,
  statusBySlug,
  providerByMethod,
  methods,
}: {
  current: string;
  statusBySlug: Map<string, ProviderAvailability> | null;
  providerByMethod: Record<string, string>;
  methods: { id: string }[];
}): string {
  if (statusBySlug === null || current === WALLET_METHOD_ID) return current;
  const isAvailable = (id: string): boolean => {
    const provider = providerByMethod[id];
    return provider !== undefined && methodVisibility(provider, statusBySlug) === "active";
  };
  if (current === "" || isAvailable(current)) return current;
  const fallback = methods.find((m) => isAvailable(m.id));
  return fallback ? fallback.id : "";
}

/**
 * True when `err` is the 409 `create_intent` raises for an order that has
 * walked past `pending_payment` (most commonly `ORDER_EXPIRY_SECONDS`
 * elapsing and the scheduler flipping it to `expired` before a retry
 * landed) — `ConflictError("order is not awaiting payment", extra=
 * {"status": order.status})` in `payments/service.py`. Matched structurally
 * on the 409 status plus the `extra.status` field that guard's `extra=`
 * keyword puts on the body (nested under `body.extra` — `app_error_handler`
 * merges `exc.extra` onto the response body), never by matching `detail`
 * text, which is shared prose with other 409s from the same endpoint (e.g.
 * the `extra.current_provider` conflict for a mismatched payment provider).
 * Mirrors `isOrderNotAwaitingPaymentConflict` in
 * `apps/web/src/lib/gift-checkout.ts`, adapted to this app's `ApiError`
 * shape, whose `body` is the raw parsed problem+json rather than a
 * pre-split `extra` field.
 */
export function isOrderNotAwaitingPaymentConflict(err: unknown): boolean {
  if (!(err instanceof ApiError) || err.status !== 409) return false;
  const body = err.body;
  if (!body || typeof body !== "object") return false;
  const extra = (body as Record<string, unknown>).extra;
  if (!extra || typeof extra !== "object") return false;
  return typeof (extra as Record<string, unknown>).status === "string";
}

/**
 * Message for a failed checkout POST. The pre-charge geo veto (ADR-0063)
 * refuses a foreign guest/fresh account with a 422 whose RFC 7807 `type`
 * ends in `/payment-unavailable-abroad` — that gets its own specific line
 * instead of the generic checkout-failed detail. Everything else falls
 * back to the API's own `detail`, or a plain retry line when there is none
 * (a network failure, a non-JSON body).
 *
 * Uses `translate` (the locale mirror), not a `t` passed in from `useT()`
 * — same choice as `providerLabel` in `OrderSuccess.tsx` — so this stays a
 * plain function callable straight from a unit test.
 */
export function checkoutErrorMessage(exc: unknown): string {
  if (exc instanceof ApiError && exc.type?.endsWith("/payment-unavailable-abroad")) {
    return translate("topup.errAbroad");
  }
  return exc instanceof ApiError ? exc.detail : translate("topup.tryAgain");
}
