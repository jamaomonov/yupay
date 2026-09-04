import { afterEach, describe, expect, test } from "vitest";

import { formatBalance, topUpAttemptKey, txKindLabelKey } from "./wallet";

import { formatMoney } from "@/lib/currency";
import { setActiveLocale } from "@/lib/i18n/core";

/**
 * Every `kind=` the backend passes to `wallet.post` today. Grep for
 * `wallet_api.post(` in apps/api to refresh. An entry here without a label is
 * a raw ledger string in the customer's wallet history — the bug this pins.
 */
const BACKEND_POSTED_KINDS = [
  "admin.adjust", // wallet/service.py
  "payment.refund", // payments/service.py
  "wallet_payment", // payments/gateways/wallet.py
  "promo.redeem", // promo/service.py
  "topup", // wallet/service.py credit_topup
  "topup.refund", // wallet/service.py reverse_topup
] as const;

describe("txKindLabelKey", () => {
  test.each(BACKEND_POSTED_KINDS)("labels %s — every posted kind must resolve", (kind) => {
    expect(txKindLabelKey(kind)).not.toBeNull();
  });

  test("maps each kind to its specific label", () => {
    // Regressions: the map keyed on "promo.grant" (never posted) instead of
    // "promo.redeem", and on "order.payment" instead of "wallet_payment" —
    // both surfaced the raw ledger key to the customer.
    expect(txKindLabelKey("promo.redeem")).toBe("wallet.tx.promo");
    expect(txKindLabelKey("wallet_payment")).toBe("wallet.tx.orderPayment");
    expect(txKindLabelKey("admin.adjust")).toBe("wallet.tx.adminAdjust");
    expect(txKindLabelKey("payment.refund")).toBe("wallet.tx.refund");
  });

  test("keeps labels for kinds wired ahead of their flows", () => {
    expect(txKindLabelKey("cashback.grant")).toBe("wallet.tx.cashback");
    expect(txKindLabelKey("topup")).toBe("wallet.tx.topup");
    expect(txKindLabelKey("topup.refund")).toBe("wallet.tx.topupRefund");
  });

  test("returns null for an unknown kind (caller shows the raw kind)", () => {
    expect(txKindLabelKey("something.else")).toBeNull();
  });
});

describe("topUpAttemptKey", () => {
  test("the same request keeps its key, so a retry replays it", () => {
    const store: { current: { signature: string; key: string } | null } = { current: null };
    const first = topUpAttemptKey(store, "50000:click_miniapp");
    expect(topUpAttemptKey(store, "50000:click_miniapp")).toBe(first);
  });

  test("a different amount is a different request", () => {
    const store: { current: { signature: string; key: string } | null } = { current: null };
    const first = topUpAttemptKey(store, "50000:click_miniapp");
    expect(topUpAttemptKey(store, "60000:click_miniapp")).not.toBe(first);
  });

  test("a different acquirer is a different request", () => {
    const store: { current: { signature: string; key: string } | null } = { current: null };
    const first = topUpAttemptKey(store, "50000:click_miniapp");
    expect(topUpAttemptKey(store, "50000:payme")).not.toBe(first);
  });
});

/**
 * The gift buy screen (`GiftGame.tsx`) renders UZS two ways on one screen:
 * `formatMoney` for the price, `formatBalance` for the wallet tile. Before
 * this fix `formatBalance` appended a static "UZS" regardless of locale
 * while `formatMoney` (once fixed) said "сум"/"soʻm" — two different tokens
 * for the same currency on the same screen (2026-09-04 review).
 */
describe("formatBalance", () => {
  afterEach(() => {
    setActiveLocale("ru");
  });

  test("agrees with formatMoney's UZS word, per locale", () => {
    for (const locale of ["ru", "en", "uz"] as const) {
      setActiveLocale(locale);
      expect(formatBalance(165_000, "UZS")).toBe(formatMoney(165_000, "UZS"));
    }
  });

  test("never renders the bare ISO code for a ru balance", () => {
    setActiveLocale("ru");
    expect(formatBalance(165_000, "UZS")).not.toMatch(/UZS/);
  });
});
