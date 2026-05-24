/**
 * Bind ⌘K / Ctrl+K to open the global search palette.
 *
 * The shortcut fires regardless of where focus currently is — operators expect
 * ⌘K to "just work" everywhere (per ADR-0017).
 */

import { useEffect } from "react";

export function useGlobalSearchHotkey(onOpen: () => void): void {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "k" && e.key !== "K") return;
      if (!(e.metaKey || e.ctrlKey)) return;
      e.preventDefault();
      onOpen();
    };
    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
    };
  }, [onOpen]);
}
