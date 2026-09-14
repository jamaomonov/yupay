import { describe, expect, it } from "vitest";

import {
  reviewDraftHasChip,
  reviewFollowUp,
  splitReviewDraft,
  toggleChipInReviewDraft,
} from "./review-draft";

describe("splitReviewDraft", () => {
  it("splits chip-style segments on '. '", () => {
    expect(splitReviewDraft("Fast. As promised. Would buy again")).toEqual([
      "Fast",
      "As promised",
      "Would buy again",
    ]);
  });

  it("keeps a free-text sentence as one segment", () => {
    expect(splitReviewDraft("дошло за минуту, всё ок")).toEqual(["дошло за минуту, всё ок"]);
  });
});

describe("toggleChipInReviewDraft", () => {
  it("appends a chip to an empty draft", () => {
    expect(toggleChipInReviewDraft("", "Fast")).toBe("Fast");
  });

  it("removes a chip already in the draft, case-insensitively", () => {
    expect(toggleChipInReviewDraft("быстро. Как обещали", "Быстро")).toBe("Как обещали");
  });

  it("does not duplicate a chip onto unrelated custom text", () => {
    const custom = "дошло очень быстро";
    expect(toggleChipInReviewDraft(custom, "Быстро")).toBe("дошло очень быстро. Быстро");
    expect(reviewDraftHasChip(toggleChipInReviewDraft(custom, "Быстро"), "Быстро")).toBe(true);
  });

  it("toggles off the exact chip without dropping the custom sentence", () => {
    const draft = "дошло очень быстро. Быстро";
    expect(toggleChipInReviewDraft(draft, "Быстро")).toBe("дошло очень быстро");
  });
});

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
