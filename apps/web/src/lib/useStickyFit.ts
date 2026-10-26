"use client";

import { type RefObject, useEffect, useState } from "react";

/** Gap kept under a sidebar that is taller than the window. */
const BOTTOM_GAP = 16;

/**
 * The `top` for a sticky sidebar that must keep its bottom reachable.
 *
 * A plain `top: 100px` pins the sidebar's head under the header; when the
 * sidebar is taller than the window its bottom — the pay button — stays below
 * the fold until the whole page has scrolled past, which on a long catalogue is
 * thousands of pixels. When the element does not fit, this returns a negative
 * `top` instead, so the page scrolls it until its bottom is `BOTTOM_GAP` above
 * the window's edge and it sticks there. Any screen height, any content height:
 * re-measured on resize of either.
 *
 * @param ref The sticky element.
 * @param preferred The `top` to use when the element fits.
 */
export function useStickyFit(ref: RefObject<HTMLElement | null>, preferred: number): number {
  const [top, setTop] = useState(preferred);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const fit = () => {
      setTop(Math.min(preferred, window.innerHeight - el.offsetHeight - BOTTOM_GAP));
    };
    fit();
    // No observer (jsdom) → the window resize still re-fits.
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(fit);
    ro?.observe(el);
    window.addEventListener("resize", fit);
    return () => {
      ro?.disconnect();
      window.removeEventListener("resize", fit);
    };
  }, [ref, preferred]);
  return top;
}
