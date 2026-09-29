import { describe, expect, it } from "vitest";

import { deliveredCopy, orderKind, shareStoryCopy } from "./order-kind";

import type { OrderOut } from "./orders";

function order(...lines: { kind: string; sku?: string }[]): OrderOut {
  return {
    items: lines.map((l, i) => ({
      id: `i${String(i)}`,
      skin_trade: null,
      display: { product_kind: l.kind, sku_code: l.sku ?? "x" },
    })),
  } as unknown as OrderOut; // only the fields orderKind reads
}

describe("orderKind", () => {
  it("tells a top-up, a code, a skin and a mixed cart apart", () => {
    expect(orderKind(order({ kind: "top_up" }))).toBe("top_up");
    expect(orderKind(order({ kind: "voucher" }))).toBe("voucher");
    expect(orderKind(order({ kind: "top_up", sku: "cs2-skin" }))).toBe("skin");
    expect(orderKind(order({ kind: "top_up" }, { kind: "voucher" }))).toBe("mixed");
  });
});

describe("deliveredCopy", () => {
  it("never calls a code or a skin a top-up", () => {
    expect(deliveredCopy(order({ kind: "voucher" })).title).toBe(
      "orderResult.delivered.voucher.title",
    );
    expect(deliveredCopy(order({ kind: "top_up", sku: "cs2-skin" })).body).toBe(
      "orderResult.delivered.skin.body",
    );
    expect(deliveredCopy(order({ kind: "top_up" })).title).toBe(
      "orderResult.delivered.topUp.title",
    );
  });
});

describe("shareStoryCopy", () => {
  it("says topped up only for a top-up", () => {
    expect(shareStoryCopy(order({ kind: "top_up" }), "PUBG")).toEqual({
      key: "success.shareStoryText",
      params: { game: "PUBG" },
    });
    expect(shareStoryCopy(order({ kind: "voucher" }), "Discord")).toEqual({
      key: "success.shareStoryTextBought",
      params: { game: "Discord" },
    });
    expect(shareStoryCopy(order({ kind: "top_up", sku: "cs2-skin" }), "Скины CS2").key).toBe(
      "success.shareStoryTextSkin",
    );
    expect(shareStoryCopy(order({ kind: "voucher" }), null).key).toBe(
      "success.shareStoryTextBoughtGeneric",
    );
  });
});
