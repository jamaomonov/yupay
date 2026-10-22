import { describe, expect, it } from "vitest";

import { amountOf, balanceOption, checkAmount, historyRow, kindKey } from "./wallet";

describe("wallet", () => {
  it("reads a typed amount as whole soʻm", () => {
    expect(amountOf("100 000")).toBe(100000);
    expect(amountOf("50000.75")).toBe(50000);
    expect(amountOf("")).toBe(0);
    expect(amountOf("12345678901")).toBe(123456789);
  });

  it("keeps a top-up inside the website's bounds", () => {
    expect(checkAmount(0)).toBe("empty");
    expect(checkAmount(4_999)).toBe("low");
    expect(checkAmount(5_000)).toBe("ok");
    expect(checkAmount(5_000_001)).toBe("high");
  });

  it("shows the buyer's own leg, signed in their favour", () => {
    const tx = (direction: "D" | "C", kind: string) => ({
      id: "t1",
      kind,
      reference_type: "order",
      reference_id: "o1",
      created_at: "2026-10-22T10:00:00Z",
      postings: [
        { account_id: "mine", direction, amount: "50000.00", currency: "UZS", created_at: "x" },
        {
          account_id: "house",
          direction: direction === "D" ? ("C" as const) : ("D" as const),
          amount: "50000.00",
          currency: "UZS",
          created_at: "x",
        },
      ],
    });
    const mine = new Set(["mine"]);
    expect(historyRow(tx("D", "topup"), mine)?.delta).toBe(50000);
    expect(historyRow(tx("C", "wallet_payment"), mine)).toMatchObject({
      delta: -50000,
      orderId: "o1",
    });
    expect(historyRow(tx("D", "topup"), new Set(["other"]))).toBeNull();
  });

  it("names every ledger kind and never shows a raw one", () => {
    expect(kindKey("topup")).toBe("wallet.tx.topUp");
    expect(kindKey("wallet_payment")).toBe("wallet.tx.payment");
    expect(kindKey("something.new")).toBe("wallet.tx.other");
  });

  it("offers the balance only when it covers the order", () => {
    expect(balanceOption(null, "1000")).toEqual({ state: "unknown" });
    expect(balanceOption("1000.00", "1000")).toEqual({ state: "ready" });
    expect(balanceOption("400", "1000.5")).toEqual({ state: "short", missing: 601 });
  });
});
