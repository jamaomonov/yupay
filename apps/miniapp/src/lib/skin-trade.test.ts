import { describe, expect, it } from "vitest";

import type { SkinTradeOut } from "./orders";

import { skinTradeView } from "./skin-trade";

const base: SkinTradeOut = {
  state: "buying",
  offer_url: null,
  send_until: null,
  release_date: null,
  seller: null,
  reason_code: null,
  refunded_to: null,
};

describe("skinTradeView", () => {
  it("says the offer is on its way while buying", () => {
    expect(skinTradeView(base)).toEqual({ kind: "buying" });
  });

  it("opens the sent offer and names seller and deadline", () => {
    expect(
      skinTradeView({
        ...base,
        state: "offer_sent",
        offer_url: "https://steamcommunity.com/tradeoffer/1/",
        send_until: "2026-09-29T10:30:00Z",
        seller: { name: "darpan", avatar_url: null, level: 3, joined_at: null },
      }),
    ).toEqual({
      kind: "offer",
      offerUrl: "https://steamcommunity.com/tradeoffer/1/",
      seller: "darpan",
      acceptBy: "2026-09-29T10:30:00Z",
    });
  });

  it("says received, with Steam's protection date while it lasts", () => {
    expect(
      skinTradeView({ ...base, state: "accepted", release_date: "2026-10-05T16:00:00Z" }),
    ).toEqual({ kind: "received", protectedUntil: "2026-10-05T16:00:00Z" });
    expect(
      skinTradeView({ ...base, state: "released", release_date: "2026-10-05T16:00:00Z" }),
    ).toEqual({ kind: "received", protectedUntil: null });
  });

  it("promises the balance only when the refund went there", () => {
    const failed = { ...base, state: "failed" as const };
    expect(
      skinTradeView({ ...failed, reason_code: "not_accepted", refunded_to: "wallet" }),
    ).toEqual({ kind: "refunded", tryLater: false });
    expect(skinTradeView({ ...failed, reason_code: "try_later", refunded_to: "wallet" })).toEqual({
      kind: "refunded",
      tryLater: true,
    });
    expect(skinTradeView({ ...failed, reason_code: "sold_out", refunded_to: "card" })).toEqual({
      kind: "refundedCard",
    });
    // A declined trade whose refund has not landed: support, not a promise.
    expect(skinTradeView({ ...failed, reason_code: "not_accepted" })).toEqual({ kind: "support" });
    expect(skinTradeView({ ...failed, reason_code: "support" })).toEqual({ kind: "support" });
  });
});
