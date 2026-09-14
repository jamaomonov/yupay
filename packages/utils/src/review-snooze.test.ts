import { describe, expect, it } from "vitest";

import { isReviewSnoozeActive, REVIEW_SNOOZE_MS, reviewSnoozeValue } from "./review-snooze";

const NOW = 1_800_000_000_000;

describe("review snooze", () => {
  it("holds for a week and then lets the prompt back", () => {
    const stored = reviewSnoozeValue(NOW);
    expect(isReviewSnoozeActive(stored, NOW)).toBe(true);
    expect(isReviewSnoozeActive(stored, NOW + REVIEW_SNOOZE_MS - 1)).toBe(true);
    expect(isReviewSnoozeActive(stored, NOW + REVIEW_SNOOZE_MS)).toBe(false);
  });

  it("never snoozes when nothing was stored", () => {
    expect(isReviewSnoozeActive(null, NOW)).toBe(false);
  });

  it("treats the old permanent marker as lapsed", () => {
    // `"1"` is what the version that never expired wrote. Honouring it forever
    // would keep the mis-taps it caused, and it carries no clock to age.
    expect(isReviewSnoozeActive("1", NOW)).toBe(false);
  });

  it("ignores anything that is not a timestamp", () => {
    expect(isReviewSnoozeActive("", NOW)).toBe(false);
    expect(isReviewSnoozeActive("later", NOW)).toBe(false);
  });
});
