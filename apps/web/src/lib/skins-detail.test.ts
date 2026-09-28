import { afterEach, describe, expect, it, vi } from "vitest";

import { getSkinDetail } from "./skins";

function answer(status: number): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response("{}", { status }))),
  );
}

describe("getSkinDetail", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("is null only when the API says the skin does not exist", async () => {
    answer(404);
    await expect(getSkinDetail("ru", "x")).resolves.toBeNull();
  });

  it("throws on an outage instead of answering 404", async () => {
    // A 404 here would tell search engines the page is gone for good.
    answer(503);
    await expect(getSkinDetail("ru", "x")).rejects.toThrow("API 503");
  });
});
