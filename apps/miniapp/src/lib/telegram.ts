/**
 * Telegram WebApp helpers.
 *
 * The official ``telegram-web-app.js`` is loaded from ``index.html`` and exposes
 * ``window.Telegram.WebApp`` synchronously. We don't use ``@telegram-apps/sdk-react``
 * here because the raw bridge is enough for what the miniapp needs today:
 *
 * - Read ``initData`` for the auth bootstrap.
 * - Call ``ready()`` so the Telegram client stops showing the loading state.
 * - Honour theme params (deferred; the app uses its own dark theme for now).
 */

export interface TelegramUser {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  photo_url?: string;
}

export interface TelegramWebApp {
  initData: string; // raw query string, signed; never trust initDataUnsafe.
  initDataUnsafe: {
    user?: TelegramUser;
    auth_date?: number;
    hash?: string;
  };
  version: string;
  platform: string;
  colorScheme: "light" | "dark";
  ready: () => void;
  expand: () => void;
  close: () => void;
  HapticFeedback?: {
    impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
    selectionChanged: () => void;
  };
  openLink?: (url: string, options?: { try_instant_view?: boolean }) => void;
  openTelegramLink?: (url: string) => void;
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

export function getWebApp(): TelegramWebApp | null {
  if (typeof window === "undefined") return null;
  return window.Telegram?.WebApp ?? null;
}

export function isInsideTelegram(): boolean {
  const wa = getWebApp();
  return Boolean(wa && wa.initData && wa.initData.length > 0);
}

/** Tell the Telegram client we're ready — hides the splash. */
export function readyTelegram(): void {
  const wa = getWebApp();
  if (wa) {
    try {
      wa.ready();
    } catch {
      /* older clients */
    }
  }
}

/**
 * Wait until ``Telegram.WebApp.initData`` is populated.
 *
 * On cold Telegram launches (especially Android) the WebView may render before
 * the official ``telegram-web-app.js`` has hydrated ``initData`` from the URL
 * hash. Calling this and awaiting the result before hitting the auth endpoint
 * removes the "have to reopen the miniapp 2–3 times" pain.
 *
 * Returns the raw initData string, or ``null`` if it never appeared within the
 * timeout (e.g. running in a plain browser).
 */
export async function waitForInitData(
  timeoutMs = 2_000,
  stepMs = 50,
): Promise<string | null> {
  const start = Date.now();
  let initData = getWebApp()?.initData ?? "";
  while (!initData && Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, stepMs));
    initData = getWebApp()?.initData ?? "";
  }
  return initData || null;
}
