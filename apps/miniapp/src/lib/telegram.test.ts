import { describe, expect, test } from "vitest";

import { computeInsetPx, computeKeyboardOpen, type Inset } from "./telegram";

const inset = (top: number, bottom: number): Inset => ({ top, right: 0, bottom, left: 0 });

describe("computeInsetPx", () => {
  test("stacks the device inset and Telegram's chrome inset", () => {
    // iPhone-shaped: dynamic island + home indicator from the device, the
    // floating close/back chip from Telegram. Content must clear both.
    expect(computeInsetPx(inset(59, 34), inset(46, 0), true)).toEqual({ top: 105, bottom: 34 });
  });

  test("handles a device with no notch and no indicator", () => {
    expect(computeInsetPx(inset(0, 0), inset(46, 0), true)).toEqual({ top: 46, bottom: 0 });
  });

  test("windowed mode keeps whatever the client reports, chip included", () => {
    // Not fullscreen: Telegram's own header sits outside the WebView, so the
    // content inset is typically 0 and we must not invent one.
    expect(computeInsetPx(inset(0, 34), inset(0, 0), false)).toEqual({ top: 0, bottom: 34 });
  });

  test("covers the chip while a fullscreen client still reports zero", () => {
    // 8.0 clients populate the insets asynchronously — a bare 0 on the first
    // paint would slide the header under the chip.
    expect(computeInsetPx(inset(0, 0), inset(0, 0), true)).toEqual({ top: 56, bottom: 0 });
  });

  test("defers to the CSS env() fallback on a pre-8.0 client", () => {
    // Nothing reported and not fullscreen → null, so we leave the stylesheet's
    // env(safe-area-inset-*) in charge rather than writing a guess.
    expect(computeInsetPx(undefined, undefined, false)).toBeNull();
  });

  test("still assumes the chip on a pre-8.0 client granted fullscreen", () => {
    expect(computeInsetPx(undefined, undefined, true)).toEqual({ top: 56, bottom: 0 });
  });

  test("tolerates a client that reports only one of the two insets", () => {
    expect(computeInsetPx(inset(59, 34), undefined, false)).toEqual({ top: 59, bottom: 34 });
    expect(computeInsetPx(undefined, inset(46, 0), false)).toEqual({ top: 46, bottom: 0 });
  });
});

describe("computeKeyboardOpen", () => {
  test("reads a full-size keyboard as open", () => {
    // iPhone 14 Pro in Telegram: ~844 stable, ~510 once the keyboard is up.
    expect(computeKeyboardOpen(510, 844)).toBe(true);
  });

  test("ignores small viewport wobble", () => {
    // Telegram's own chrome shifting a few px must not yank the nav away.
    expect(computeKeyboardOpen(800, 844)).toBe(false);
  });

  test("treats a settled viewport as closed", () => {
    expect(computeKeyboardOpen(844, 844)).toBe(false);
  });

  test("stays closed when the client reports nothing", () => {
    // Pre-6.1 clients and plain browsers — layout must not change at all.
    expect(computeKeyboardOpen(undefined, undefined)).toBe(false);
    expect(computeKeyboardOpen(510, undefined)).toBe(false);
  });
});
