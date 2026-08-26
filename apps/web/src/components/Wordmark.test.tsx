import { describe, expect, test } from "vitest";

import { Wordmark } from "./Wordmark";

/**
 * The wordmark must not go through the image optimizer.
 *
 * Next does not rasterize SVG: measured on production, `/_next/image?url=…
 * wordmark.svg&w=256` returns the file byte-for-byte identical to
 * `/logo/wordmark.svg` — 3981 bytes either way. So the optimizer round trip
 * buys nothing and costs 433ms of TTFB against 273ms for the plain file,
 * because the optimizer path is not edge-cached and the plain one is.
 *
 * `priority` made it worse: it emits a `<link rel="preload" as="image">`, so a
 * header logo that changes nothing about the page was preloading ahead of the
 * hero, which is the actual LCP element.
 */
describe("Wordmark", () => {
  test("bypasses the optimizer and does not preload", () => {
    const el = Wordmark({});
    expect(el.props.unoptimized).toBe(true);
    expect(el.props.priority).toBeFalsy();
  });

  test("still renders the brand lockup at both sizes", () => {
    expect(Wordmark({}).props.src).toBe("/logo/wordmark.svg");
    expect(Wordmark({ size: "sm" }).props.height).toBe(24);
    expect(Wordmark({}).props.height).toBe(30);
  });
});
