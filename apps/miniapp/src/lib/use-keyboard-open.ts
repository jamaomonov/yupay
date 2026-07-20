/**
 * `true` while the on-screen keyboard is up.
 *
 * Telegram reports it indirectly: `viewportHeight` shrinks to what's visible
 * while `viewportStableHeight` holds the last settled value, so the gap between
 * them is the keyboard. Outside Telegram — and on clients that report neither —
 * this stays `false`, which keeps the layout exactly as it was.
 */

import { useEffect, useState } from "react";

import { getWebApp, isKeyboardOpen } from "./telegram";

export function useKeyboardOpen(): boolean {
  const [open, setOpen] = useState(() => isKeyboardOpen());

  useEffect(() => {
    const wa = getWebApp();
    if (!wa || typeof wa.onEvent !== "function") return;
    const handler = () => {
      setOpen(isKeyboardOpen());
    };
    try {
      wa.onEvent("viewportChanged", handler);
    } catch {
      return;
    }
    return () => {
      try {
        wa.offEvent?.("viewportChanged", handler);
      } catch {
        /* ignore */
      }
    };
  }, []);

  return open;
}
