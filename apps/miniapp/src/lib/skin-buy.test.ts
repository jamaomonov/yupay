import { describe, expect, it } from "vitest";

import { ApiError } from "./api";
import { orderKeyFor, skinBuyFailure, tradeLinkShapeOk, tradeLinkVerdict } from "./skin-buy";

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

  it("keeps the key for a retry of the same offer", () => {
    expect(orderKeyFor({ listingId: 1, key: "k1" }, 1, mint)).toEqual({ listingId: 1, key: "k1" });
  });

  it("mints a new key for another offer or the first try", () => {
    expect(orderKeyFor({ listingId: 1, key: "k1" }, 2, mint)).toEqual({
      listingId: 2,
      key: "fresh",
    });
    expect(orderKeyFor(null, 1, mint)).toEqual({ listingId: 1, key: "fresh" });
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
