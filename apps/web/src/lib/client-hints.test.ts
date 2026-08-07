// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { collectClientHints } from "./client-hints";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("collectClientHints", () => {
  it("reports the signals a dispute pack corroborates against", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("ru-RU");
    vi.stubGlobal("screen", { width: 412, height: 915 });
    vi.stubGlobal("devicePixelRatio", 2.625);

    const hints = collectClientHints();

    expect(hints?.locale).toBe("ru-RU");
    // devicePixelRatio is rounded: the raw value shifts with browser zoom on
    // one and the same device, which would read as a mismatch later.
    expect(hints?.screen).toBe("412x915@2.6");
    expect(typeof hints?.timezone).toBe("string");
  });

  it("omits a signal the browser withholds instead of sending an empty one", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("");
    vi.stubGlobal("screen", { width: 0, height: 0 });

    const hints = collectClientHints();

    expect(hints).not.toHaveProperty("locale");
    expect(hints).not.toHaveProperty("screen");
  });

  it("survives a browser that refuses to resolve a timezone", () => {
    // A locked-down or unusual environment can throw out of Intl. Checkout must
    // not care — evidence is a nice-to-have next to completing the sale.
    vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.stubGlobal("screen", { width: 390, height: 844 });
    vi.stubGlobal("devicePixelRatio", 3);

    const hints = collectClientHints();

    expect(hints).not.toHaveProperty("timezone");
    expect(hints?.screen).toBe("390x844@3");
  });

  it("collects nothing at all rather than an empty object", () => {
    vi.spyOn(navigator, "language", "get").mockReturnValue("");
    vi.stubGlobal("screen", { width: 0, height: 0 });
    vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => {
      throw new Error("blocked");
    });

    // Undefined keeps the key out of the request body entirely, which is what
    // lets the server tell "not reported" apart from "reported as blank".
    expect(collectClientHints()).toBeUndefined();
  });
});
