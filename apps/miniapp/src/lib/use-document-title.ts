/**
 * Update ``document.title`` for the current SPA route.
 *
 * Telegram's WebView treats this as the window title (visible when the user
 * shares the app or when assistive tech reads the page heading on navigation).
 * Without this every route reported the same hard-coded "YuPay — Mini App"
 * which fails WCAG 2.4.2 ("Page Titled").
 */

import { useEffect } from "react";

const BASE = "YuPay";

export function useDocumentTitle(label: string | null | undefined): void {
  useEffect(() => {
    const next = label ? `${label} · ${BASE}` : BASE;
    const previous = document.title;
    document.title = next;
    // Restore on unmount so a subsequent route still sets its own title even
    // if it forgets to call this hook — defensive, not strictly required.
    return () => {
      document.title = previous;
    };
  }, [label]);
}
