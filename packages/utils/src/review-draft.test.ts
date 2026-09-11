import { describe, expect, it } from "vitest";

import { reviewDraftHasChip, splitReviewDraft, toggleChipInReviewDraft } from "./review-draft";

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
