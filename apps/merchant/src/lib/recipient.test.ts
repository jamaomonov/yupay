import { describe, expect, it } from "vitest";

import { recipientLines, visibleArtifactLines } from "./recipient";

const field = {
  key: "server",
  label: { ru: "Сервер", en: "Server" },
  value: "2045",
  value_label: { ru: "Азия", en: "Asia" },
};

describe("recipientLines", () => {
  it("labels each value in the cabinet's locale", () => {
    expect(recipientLines([field], "en")).toEqual([
      { key: "server", label: "Server", value: "2045", shown: "Asia" },
    ]);
  });

  it("falls back to Russian, then to the key", () => {
    expect(recipientLines([field], "uz")[0]?.label).toBe("Сервер");
    expect(
      recipientLines([{ key: "zone", label: {}, value: "1", value_label: null }], "en"),
    ).toEqual([{ key: "zone", label: "zone", value: "1", shown: "1" }]);
  });

  it("treats a missing list from an older API as empty", () => {
    expect(recipientLines(undefined, "ru")).toEqual([]);
  });
});

describe("visibleArtifactLines", () => {
  it("drops the supplier's bookkeeping keys and keeps what was handed over", () => {
    expect(
      visibleArtifactLines({ status: "shipped", kind: "topup_receipt", code: "AB-12" }),
    ).toEqual([{ key: "code", value: "AB-12" }]);
  });

  it("splits a list of codes into numbered lines", () => {
    expect(visibleArtifactLines({ codes: ["A", "B"] })).toEqual([
      { key: "codes[0]", value: "A" },
      { key: "codes[1]", value: "B" },
    ]);
  });
});
