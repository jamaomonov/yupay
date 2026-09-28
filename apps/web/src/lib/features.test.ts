import { afterEach, describe, expect, it } from "vitest";

import { skinsEnabled } from "./features";

describe("skinsEnabled", () => {
  afterEach(() => {
    delete process.env.SKINS_ENABLED;
  });

  it("is off unless the env says exactly true", () => {
    expect(skinsEnabled()).toBe(false);
    process.env.SKINS_ENABLED = "1";
    expect(skinsEnabled()).toBe(false);
    process.env.SKINS_ENABLED = "true";
    expect(skinsEnabled()).toBe(true);
  });
});
