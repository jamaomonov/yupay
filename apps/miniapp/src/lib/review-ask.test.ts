// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import {
  catchUpAllowedOn,
  dismissReviewAsk,
  isReviewAskDismissed,
  parseReviewLaunchParam,
} from "./review-ask";

afterEach(() => {
  try {
    window.localStorage.clear();
  } catch {
    /* node env without localStorage */
  }
});

describe("parseReviewLaunchParam", () => {
  const id = "11111111-1111-1111-1111-111111111111";

  it("reads ?review= from the Mini App URL", () => {
    expect(parseReviewLaunchParam(`?review=${id}`, undefined)).toBe(id);
  });

  it("reads Telegram start_param with a review_ prefix", () => {
    expect(parseReviewLaunchParam("", `review_${id}`)).toBe(id);
  });

  it("rejects junk", () => {
    expect(parseReviewLaunchParam("?review=not-an-id", undefined)).toBeNull();
    expect(parseReviewLaunchParam("", undefined)).toBeNull();
  });
});

describe("catchUpAllowedOn", () => {
  it("allows home and history only", () => {
    expect(catchUpAllowedOn("/")).toBe(true);
    expect(catchUpAllowedOn("/history")).toBe(true);
    expect(catchUpAllowedOn("/topup/pubg")).toBe(false);
    expect(catchUpAllowedOn("/order/abc")).toBe(false);
  });
});

describe("dismiss storage", () => {
  it("remembers a dismissed order", () => {
    const id = "11111111-1111-1111-1111-111111111111";
    expect(isReviewAskDismissed(id)).toBe(false);
    dismissReviewAsk(id);
    expect(isReviewAskDismissed(id)).toBe(true);
  });
});
