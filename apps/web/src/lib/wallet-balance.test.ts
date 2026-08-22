import { describe, expect, test } from "vitest";

import { canPayFromBalance, spendableBalance, walletTile } from "./wallet-balance";

const UZS = "UZS";

describe("spendableBalance", () => {
  test("null before the query resolves, so the tile can say 'not yet' rather than 'no money'", () => {
    expect(spendableBalance(null, UZS)).toBeNull();
    expect(spendableBalance(undefined, UZS)).toBeNull();
  });

  test("zero when the account does not exist yet — a customer who never topped up", () => {
    expect(spendableBalance([], UZS)).toBe(0);
  });

  test("reads the wallet account in the asked-for currency", () => {
    const balances = [
      {
        account_id: "acc-user_wallet-UZS",
        kind: "user_wallet",
        currency: "UZS",
        balance: "125000.000000",
      },
      {
        account_id: "acc-user_wallet-USDT",
        kind: "user_wallet",
        currency: "USDT",
        balance: "40.000000",
      },
    ];
    expect(spendableBalance(balances, UZS)).toBe(125000);
    expect(spendableBalance(balances, "USDT")).toBe(40);
  });

  test("ignores cashback and promo credit", () => {
    // They are in the same response and the same ledger, but nothing spends
    // them yet — counting them would offer a payment the gateway refuses.
    const balances = [
      {
        account_id: "acc-user_wallet-UZS",
        kind: "user_wallet",
        currency: "UZS",
        balance: "1000.000000",
      },
      {
        account_id: "acc-user_cashback-UZS",
        kind: "user_cashback",
        currency: "UZS",
        balance: "50000.000000",
      },
      {
        account_id: "acc-user_promo_credit-UZS",
        kind: "user_promo_credit",
        currency: "UZS",
        balance: "90000.000000",
      },
    ];
    expect(spendableBalance(balances, UZS)).toBe(1000);
  });

  test("a malformed amount reads as empty, never as NaN", () => {
    expect(
      spendableBalance(
        [{ account_id: "acc-user_wallet-UZS", kind: "user_wallet", currency: UZS, balance: "-" }],
        UZS,
      ),
    ).toBe(0);
  });
});

describe("walletTile", () => {
  test("a guest is offered the way in, whatever the totals", () => {
    expect(walletTile({ isLoggedIn: false, balance: null, total: 159635 })).toEqual({
      state: "guest",
    });
  });

  test("no verdict while the balance is still loading", () => {
    expect(walletTile({ isLoggedIn: true, balance: null, total: 159635 })).toEqual({
      state: "unknown",
    });
  });

  test("no verdict before a package is chosen — there is nothing to compare against", () => {
    expect(walletTile({ isLoggedIn: true, balance: 500000, total: null })).toEqual({
      state: "unknown",
    });
    expect(walletTile({ isLoggedIn: true, balance: 500000, total: 0 })).toEqual({
      state: "unknown",
    });
  });

  test("ready when the balance covers the order", () => {
    expect(walletTile({ isLoggedIn: true, balance: 200000, total: 159635 })).toEqual({
      state: "ready",
      balance: 200000,
    });
  });

  test("exactly enough is enough", () => {
    expect(walletTile({ isLoggedIn: true, balance: 159635, total: 159635 })).toEqual({
      state: "ready",
      balance: 159635,
    });
  });

  test("short by the difference", () => {
    expect(walletTile({ isLoggedIn: true, balance: 12500, total: 57500 })).toEqual({
      state: "short",
      balance: 12500,
      missing: 45000,
    });
  });

  test("a fractional shortfall rounds up — an acquirer will not take part of a soum", () => {
    const tile = walletTile({ isLoggedIn: true, balance: 100, total: 144.4 });
    expect(tile).toEqual({ state: "short", balance: 100, missing: 45 });
  });

  test("an empty wallet is short, not unknown", () => {
    expect(walletTile({ isLoggedIn: true, balance: 0, total: 5000 })).toEqual({
      state: "short",
      balance: 0,
      missing: 5000,
    });
  });
});

describe("canPayFromBalance", () => {
  test("only a ready tile pays", () => {
    expect(canPayFromBalance({ state: "ready", balance: 1 })).toBe(true);
    expect(canPayFromBalance({ state: "short", balance: 1, missing: 1 })).toBe(false);
    expect(canPayFromBalance({ state: "guest" })).toBe(false);
    expect(canPayFromBalance({ state: "unknown" })).toBe(false);
  });
});
