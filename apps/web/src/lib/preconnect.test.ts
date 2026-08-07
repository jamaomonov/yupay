import { afterEach, describe, expect, it } from "vitest";

import { apiPreconnectOrigin } from "./preconnect";

const SITE = "https://yupay.uz";

afterEach(() => {
  delete process.env.NEXT_PUBLIC_API_BASE_URL;
});

describe("apiPreconnectOrigin", () => {
  it("returns the API origin when it is a separate host", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.yupay.uz";
    expect(apiPreconnectOrigin(SITE)).toBe("https://api.yupay.uz");
  });

  it("strips any path so the hint is a bare origin", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.yupay.uz/api/v1/";
    expect(apiPreconnectOrigin(SITE)).toBe("https://api.yupay.uz");
  });

  it("emits nothing when the API is same-origin", () => {
    // The connection already exists — hinting at it wastes a slot and shows up
    // in Lighthouse as an unused preconnect.
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://yupay.uz/api";
    expect(apiPreconnectOrigin(SITE)).toBeNull();
  });

  it("stays silent when the var is unset or unparseable", () => {
    expect(apiPreconnectOrigin(SITE)).toBeNull();
    process.env.NEXT_PUBLIC_API_BASE_URL = "not a url";
    expect(apiPreconnectOrigin(SITE)).toBeNull();
  });
});
