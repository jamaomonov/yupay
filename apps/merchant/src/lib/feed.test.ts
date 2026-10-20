import { describe, expect, it } from "vitest";

import type { P2PDeposit, Transaction } from "./types";

import { mergeFeed } from "./feed";

function tx(id: string, at: string): Transaction {
  return {
    transaction_id: id,
    kind: "merchant_order_charge",
    amount_usd: "-1.00",
    order_id: null,
    merchant_order_id: null,
    description: null,
    order_title: null,
    brand_logo_url: null,
    created_at: at,
  };
}

function req(number: string, status: P2PDeposit["status"], at: string): P2PDeposit {
  return {
    number,
    status,
    amount_uzs: 1,
    amount_usd: "1.00",
    fx_rate: "1",
    created_at: at,
    expires_at: at,
    closed_at: null,
    card: null,
  };
}

describe("mergeFeed", () => {
  it("puts unpaid requests among movements by time and leaves paid ones to the ledger", () => {
    const feed = mergeFeed(
      [tx("a", "2026-10-20T10:00:00Z"), tx("b", "2026-10-20T08:00:00Z")],
      [
        req("T-3", "pending", "2026-10-20T11:00:00Z"),
        req("T-2", "paid", "2026-10-20T09:30:00Z"),
        req("T-1", "expired", "2026-10-20T09:00:00Z"),
      ],
      false,
    );
    expect(
      feed.map((e) => (e.type === "movement" ? e.row.transaction_id : e.deposit.number)),
    ).toEqual(["T-3", "a", "T-1", "b"]);
  });

  it("holds back a request older than the last loaded movement while more are coming", () => {
    const feed = mergeFeed(
      [tx("a", "2026-10-20T10:00:00Z")],
      [req("T-1", "expired", "2026-10-19T09:00:00Z")],
      true,
    );
    expect(feed).toHaveLength(1);
  });
});
