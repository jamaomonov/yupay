/**
 * Wires ``Telegram.WebApp.BackButton`` to the active wouter route.
 *
 * Telegram clients render the title-bar control as either an "×" (close the
 * Mini App) or a "←" (back). The "←" appears only while ``BackButton`` is
 * marked visible. We expose it on every non-root route and tie the tap to
 * the browser history so navigation feels native — the same gesture works
 * whether the user came in via a deep link, the bot menu, or in-app
 * navigation.
 */

import { useEffect } from "react";
import { useLocation } from "wouter";

import { getWebApp } from "./telegram";

const ROOT_PATHS = new Set(["/", ""]);

export function useTelegramBackButton(): void {
  const [location, setLocation] = useLocation();

  useEffect(() => {
    const backButton = getWebApp()?.BackButton;
    if (!backButton) return;

    if (ROOT_PATHS.has(location)) {
      backButton.hide();
      return;
    }

    const handler = () => {
      // Prefer the real browser history so multi-step flows (e.g. Home →
      // TopUp → OrderSuccess) walk back step-by-step instead of jumping
      // straight to Home. When the user opened a deep link there is no
      // history to walk, so fall back to Home.
      if (window.history.length > 1) {
        window.history.back();
      } else {
        setLocation("/");
      }
    };

    backButton.onClick(handler);
    backButton.show();

    return () => {
      backButton.offClick(handler);
      backButton.hide();
    };
  }, [location, setLocation]);
}
