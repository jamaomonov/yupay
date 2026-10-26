// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useStickyFit } from "./useStickyFit";

function sidebar(height: number): { current: HTMLElement } {
  const el = document.createElement("aside");
  Object.defineProperty(el, "offsetHeight", { value: height });
  return { current: el };
}

describe("useStickyFit", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the preferred top when the sidebar fits the window", () => {
    vi.stubGlobal("innerHeight", 1000);
    const { result } = renderHook(() => useStickyFit(sidebar(700), 100));
    expect(result.current).toBe(100);
  });

  it("lowers the top so the bottom of a tall sidebar stays on screen", () => {
    // A 13-inch laptop: 780px of window, an 867px order form.
    vi.stubGlobal("innerHeight", 780);
    const { result } = renderHook(() => useStickyFit(sidebar(867), 100));
    expect(result.current).toBe(780 - 867 - 16);
  });
});
