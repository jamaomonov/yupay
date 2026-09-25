import { describe, expect, it } from "vitest";

import { reviewFollowUp } from "./review-draft";

describe("reviewFollowUp", () => {
  it("asks for stars when there is no review", () => {
    expect(reviewFollowUp(null)).toBe("ask");
    expect(reviewFollowUp(undefined)).toBe("ask");
  });

  it("asks for words when a review was rated but never written on", () => {
    // The state the old "hide once reviewed" rule discarded, and the only one
    // that turns a star into a sentence.
    expect(reviewFollowUp({ body: null, can_add_text: true })).toBe("words");
    expect(reviewFollowUp({ body: "   ", can_add_text: true })).toBe("words");
  });

  it("stops asking once the words exist", () => {
    expect(reviewFollowUp({ body: "пришло за минуту", can_add_text: true })).toBe("settled");
  });

  it("stops asking once the window has closed, written or not", () => {
    // Offering a box the next request would refuse is worse than not offering
    // one — the server owns `can_add_text`, and this trusts it.
    expect(reviewFollowUp({ body: null, can_add_text: false })).toBe("settled");
    expect(reviewFollowUp({ body: "поздно", can_add_text: false })).toBe("settled");
  });
});
