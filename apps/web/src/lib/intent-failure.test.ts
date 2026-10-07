import { describe, expect, it } from "vitest";

import { parseIntentFailure } from "./intent-failure";

describe("parseIntentFailure", () => {
  it("reads the ledger's have/need out of a 409 wallet refusal", () => {
    const f = parseIntentFailure(409, {
      type: "https://yupay.uz/problems/conflict",
      detail:
        "payment provider rejected the request: insufficient wallet balance: have 52821.000000 UZS, need 53667.000000 UZS",
    });
    expect(f).toEqual({ kind: "insufficient_balance", have: 52821, need: 53667 });
  });

  it("still names the refusal when the numbers are missing", () => {
    expect(parseIntentFailure(409, { detail: "insufficient wallet balance" })).toEqual({
      kind: "insufficient_balance",
      have: null,
      need: null,
    });
  });

  it("treats every other refusal as 'other'", () => {
    expect(parseIntentFailure(409, { detail: "provider p2p is disabled" })).toEqual({
      kind: "other",
    });
    expect(parseIntentFailure(500, null)).toEqual({ kind: "other" });
    expect(parseIntentFailure(200, { detail: "insufficient wallet balance" })).toEqual({
      kind: "other",
    });
  });
});
