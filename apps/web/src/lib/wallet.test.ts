import { describe, expect, test } from "vitest";

import { summarizeForUser, TX_KIND_LABEL, txKindLabelKey, type WalletTransaction } from "./wallet";

/**
 * Every `kind=` the backend passes to `wallet.post` today. Grep for
 * `wallet_api.post(` and `svc.post(` in apps/api to refresh. An entry missing
 * here is a raw ledger string in the customer's history — the bug this pins.
 */
const BACKEND_KINDS = [
  "admin.adjust",
  "payment.refund",
  "wallet_payment",
  "promo.redeem",
  "cashback.grant",
  "topup",
  "topup.refund",
];

const MY_ACCOUNT = "acc-mine";

function tx(over: Partial<WalletTransaction> = {}): WalletTransaction {
  return {
    id: "tx-1",
    kind: "topup",
    reference_type: "payment",
    reference_id: "pay-1",
    actor: "payments.topup",
    extra_metadata: {},
    created_at: "2026-08-22T10:00:00Z",
    postings: [
      {
        id: "p-1",
        account_id: MY_ACCOUNT,
        direction: "D",
        amount: "50000.000000",
        currency: "UZS",
        created_at: "2026-08-22T10:00:00Z",
      },
      {
        id: "p-2",
        account_id: "acc-house",
        direction: "C",
        amount: "50000.000000",
        currency: "UZS",
        created_at: "2026-08-22T10:00:00Z",
      },
    ],
    ...over,
  };
}

describe("summarizeForUser", () => {
  const mine = new Set([MY_ACCOUNT]);

  test("a debit on the customer's account raises the balance", () => {
    // `user_wallet` is normal-D. Reading this backwards would render every
    // top-up as a withdrawal.
    expect(summarizeForUser(tx(), mine)?.delta).toBe(50000);
  });

  test("a credit lowers it", () => {
    const spend = tx({
      kind: "wallet_payment",
      postings: [
        {
          id: "p-1",
          account_id: MY_ACCOUNT,
          direction: "C",
          amount: "13438.000000",
          currency: "UZS",
          created_at: "2026-08-22T11:00:00Z",
        },
      ],
    });
    expect(summarizeForUser(spend, mine)?.delta).toBe(-13438);
  });

  test("picks the customer's leg, not the house one", () => {
    const view = summarizeForUser(tx(), mine);
    expect(view?.currency).toBe("UZS");
    expect(view?.kind).toBe("topup");
  });

  test("null when nothing touched the customer's accounts", () => {
    expect(summarizeForUser(tx(), new Set(["someone-else"]))).toBeNull();
  });

  test("a malformed amount reads as zero, never NaN", () => {
    const broken = tx({
      postings: [
        {
          id: "p-1",
          account_id: MY_ACCOUNT,
          direction: "D",
          amount: "oops",
          currency: "UZS",
          created_at: "2026-08-22T10:00:00Z",
        },
      ],
    });
    expect(summarizeForUser(broken, mine)?.delta).toBe(0);
  });
});

describe("txKindLabelKey", () => {
  test.each(BACKEND_KINDS)("%s has a label", (kind) => {
    expect(txKindLabelKey(kind)).not.toBeNull();
  });

  test("an unknown kind falls through rather than throwing", () => {
    expect(txKindLabelKey("something.new")).toBeNull();
  });

  test("no label is mapped twice — each kind reads distinctly in the history", () => {
    const keys = Object.values(TX_KIND_LABEL);
    expect(new Set(keys).size).toBe(keys.length);
  });
});
