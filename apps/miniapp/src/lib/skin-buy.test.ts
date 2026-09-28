import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import {
  afterListingGone,
  tradeLinkAccount,
  oneAtATime,
  cheapestOffer,
  orderKeyFor,
  skinBuyFailure,
  tradeLinkShapeOk,
  tradeLinkVerdict,
} from "./skin-buy";

const unprocessable = (extra: Record<string, unknown>) =>
  new ApiError(422, "Unprocessable", { detail: "x", extra });

describe("skinBuyFailure", () => {
  it("reads a moved price", () => {
    expect(skinBuyFailure(unprocessable({ expected_amount_usd: "31.50" }))).toEqual({
      kind: "priceChanged",
      expectedUsd: "31.50",
    });
  });

  it("reads a sold offer with the next one", () => {
    expect(
      skinBuyFailure(
        unprocessable({
          reason: "listing_gone",
          next_offer: { listing_id: 7, price_usd: "32.00" },
        }),
      ),
    ).toEqual({ kind: "listingGone", next: { listing_id: 7, price_usd: "32.00" } });
  });

  it("reads a sold offer with none left", () => {
    expect(skinBuyFailure(unprocessable({ reason: "listing_gone", next_offer: null }))).toEqual({
      kind: "listingGone",
      next: null,
    });
  });

  it("reads a trade link from another account", () => {
    expect(skinBuyFailure(unprocessable({ reason: "tradelink_other_account" }))).toEqual({
      kind: "tradelink",
      reason: "tradelink_other_account",
    });
  });

  it("leaves every other error to the generic message", () => {
    expect(skinBuyFailure(new ApiError(409, "Conflict", { detail: "x" }))).toBeNull();
    expect(skinBuyFailure(unprocessable({ reason: "something_else" }))).toBeNull();
    expect(skinBuyFailure(new Error("network"))).toBeNull();
  });
});

describe("orderKeyFor", () => {
  const mint = () => "fresh";
  const k1 = { listingId: 1, tradelink: "A", key: "k1" };

  it("keeps the key for a retry of the same offer to the same link", () => {
    expect(orderKeyFor(k1, 1, "A", mint)).toEqual(k1);
  });

  it("mints a new key for another offer, another trade link, or the first try", () => {
    expect(orderKeyFor(k1, 2, "A", mint)).toEqual({ listingId: 2, tradelink: "A", key: "fresh" });
    // A replayed order would still deliver to the old link.
    expect(orderKeyFor(k1, 1, "B", mint)).toEqual({ listingId: 1, tradelink: "B", key: "fresh" });
    expect(orderKeyFor(null, 1, "A", mint)).toEqual({ listingId: 1, tradelink: "A", key: "fresh" });
  });
});

describe("tradeLinkShapeOk", () => {
  it("accepts a Steam trade link and nothing else", () => {
    expect(
      tradeLinkShapeOk(
        "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=abcDEF12",
      ),
    ).toBe(true);
    expect(
      tradeLinkShapeOk("  https://steamcommunity.com/tradeoffer/new/?partner=1&token=abcdef "),
    ).toBe(true);
    expect(tradeLinkShapeOk("https://steamcommunity.com/id/someone")).toBe(false);
    expect(tradeLinkShapeOk("")).toBe(false);
  });
});

describe("tradeLinkVerdict", () => {
  it("lets a working link pay and says so", () => {
    expect(tradeLinkVerdict({ ok: true, reason: null })).toEqual({ line: "ok", usable: true });
  });

  it("never blocks on an unavailable check and says nothing", () => {
    expect(tradeLinkVerdict({ ok: true, reason: "unavailable" })).toEqual({
      line: null,
      usable: true,
    });
    expect(tradeLinkVerdict(null)).toEqual({ line: null, usable: true });
  });

  it("blocks a private inventory, a ban or a hold", () => {
    expect(tradeLinkVerdict({ ok: false, reason: "private" })).toEqual({
      line: "private",
      usable: false,
    });
    expect(tradeLinkVerdict({ ok: false, reason: "hold" })).toEqual({
      line: "hold",
      usable: false,
    });
  });
});

describe("cheapestOffer", () => {
  it("picks by the dollar price, numerically", () => {
    const offers = [
      { listing_id: 1, price_usd: "100.00" },
      { listing_id: 2, price_usd: "9.50" },
      { listing_id: 3, price_usd: "31.00" },
    ];
    expect(cheapestOffer(offers)?.listing_id).toBe(2);
    expect(cheapestOffer([])).toBeNull();
  });
});

describe("afterListingGone", () => {
  const offers = [
    { listing_id: 1, price_usd: "30.00" },
    { listing_id: 2, price_usd: "31.00" },
    { listing_id: 3, price_usd: "33.00" },
  ];

  it("drops the sold offer and selects the next one the server named", () => {
    const r = afterListingGone(offers, 1, { listing_id: 3, price_usd: "33.00" });
    expect(r.offers.map((o) => o.listing_id)).toEqual([2, 3]);
    expect(r.selected?.listing_id).toBe(3);
  });

  it("falls back to the cheapest remaining when the named one is not on the page", () => {
    const r = afterListingGone(offers, 1, { listing_id: 99, price_usd: "35.00" });
    expect(r.selected?.listing_id).toBe(2);
  });

  it("selects nothing when none are left", () => {
    expect(afterListingGone([offers[0]!], 1, null).selected).toBeNull();
  });
});

describe("oneAtATime", () => {
  it("ignores a second tap while the first purchase is still running", async () => {
    let calls = 0;
    let finish: () => void = () => undefined;
    const buy = oneAtATime(async () => {
      calls += 1;
      await new Promise<void>((resolve) => {
        finish = resolve;
      });
    });
    const first = buy();
    void buy();
    finish();
    await first;
    expect(calls).toBe(1);
    const again = buy();
    finish();
    await again;
    expect(calls).toBe(2);
  });

  it("frees itself when the purchase fails", async () => {
    let calls = 0;
    const buy = oneAtATime(async () => {
      calls += 1;
      throw new Error("no");
    });
    await buy().catch(() => undefined);
    await buy().catch(() => undefined);
    expect(calls).toBe(2);
  });
});

describe("tradeLinkAccount", () => {
  it("names the Steam account a trade goes to, never the token", () => {
    expect(
      tradeLinkAccount(
        "https://steamcommunity.com/tradeoffer/new/?partner=1039652352&token=LBCWEQ8s",
      ),
    ).toBe("1039652352");
    expect(tradeLinkAccount("not a link")).toBeNull();
  });
});
