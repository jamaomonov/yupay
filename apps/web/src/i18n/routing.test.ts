import { describe, expect, test } from "vitest";

import { routing } from "./routing";

describe("locale cookie", () => {
  test("no Set-Cookie on HTML, because Cloudflare will not cache a response that has one", () => {
    // The middleware set NEXT_LOCALE on every page response, which made Next
    // mark them uncacheable at the edge. Nothing reads the cookie: detection is
    // off, and a grep across apps/ and packages/ finds no consumer. So it was
    // costing every ad click an origin render and buying nothing.
    expect(routing.localeCookie).toBe(false);
  });

  test("locale still comes from the URL, for all three languages", () => {
    // What the cookie would otherwise have remembered is a manual switch. This
    // app does not lean on that: the switcher is a set of links, so the choice
    // lives in the URL the visitor lands on and survives in history.
    expect(routing.localeDetection).toBe(false);
    expect(routing.localePrefix).toBe("as-needed");
    expect(routing.locales).toEqual(expect.arrayContaining(["ru", "en", "uz"]));
  });
});
