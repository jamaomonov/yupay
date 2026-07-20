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

export interface TelegramBackButton {
  isVisible: boolean;
  show: () => void;
  hide: () => void;
  onClick: (cb: () => void) => void;
  offClick: (cb: () => void) => void;
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
  isExpanded?: boolean;
  isFullscreen?: boolean;
  // Safe-area insets exposed by Bot API 8.0+ (Dec 2024). They also land
  // on ``document.documentElement`` as ``--tg-safe-area-inset-*`` /
  // ``--tg-content-safe-area-inset-*`` CSS vars, which is what the UI
  // actually reads.
  safeAreaInset?: { top: number; right: number; bottom: number; left: number };
  contentSafeAreaInset?: { top: number; right: number; bottom: number; left: number };
  ready: () => void;
  expand: () => void;
  // Available since Bot API 6.1; lets us gate newer methods by client version
  // instead of mere existence (telegram-web-app.js defines them on every
  // client and logs a console error itself when the version is too old).
  isVersionAtLeast?: (version: string) => boolean;
  // Bot API 8.0+. Falls back to a no-op on older clients; we feature-detect.
  requestFullscreen?: () => void;
  exitFullscreen?: () => void;
  // Bot API 7.7+.
  disableVerticalSwipes?: () => void;
  // Bot API 6.1+. ``bg_color`` is the area outside the WebView (e.g.
  // the strip behind the close/back chip when in fullscreen); the
  // ``themeParams`` keys ``"bg_color"`` and ``"secondary_bg_color"``
  // are accepted as well.
  setBackgroundColor?: (color: string) => void;
  setHeaderColor?: (color: string) => void;
  close: () => void;
  // Available since Bot API 6.1 (mid-2022) — every supported Telegram client
  // has it. When visible the client swaps the title-bar "×" for a "←", so we
  // get native back-navigation that feels exactly like other Mini Apps.
  BackButton?: TelegramBackButton;
  HapticFeedback?: {
    impactOccurred: (style: "light" | "medium" | "heavy" | "rigid" | "soft") => void;
    notificationOccurred: (type: "error" | "success" | "warning") => void;
    selectionChanged: () => void;
  };
  openLink?: (url: string, options?: { try_instant_view?: boolean }) => void;
  openTelegramLink?: (url: string) => void;
  // Bot API 6.1+. The events we care about are 8.0+ (`safeAreaChanged`,
  // `contentSafeAreaChanged`, `fullscreenChanged`); subscribing on an older
  // client is harmless, they simply never fire.
  onEvent?: (event: string, handler: () => void) => void;
  offEvent?: (event: string, handler: () => void) => void;
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
 * Maximise viewport real estate inside the Telegram client.
 *
 * Calls in this order:
 *   1. ``expand()`` — widely supported (Bot API 6.0+), turns the mini app
 *      into a full-height sheet that doesn't collapse on scroll-up.
 *   2. ``requestFullscreen()`` — Bot API 8.0+ (Dec 2024). Hides the
 *      Telegram chat headers on supported clients, leaving only the
 *      close / back controls as a floating overlay.
 *   3. ``disableVerticalSwipes()`` — also 8.0+. Without it Android
 *      Telegram dismisses the WebView on a downward swipe even when in
 *      fullscreen, which conflicts with our scroll containers.
 *
 * Every step is feature-detected and try/catch'd so legacy clients are
 * unaffected.
 */
export function maximiseTelegramViewport(): void {
  // Dev shortcut: outside Telegram, append ``?tg-fullscreen=1`` to preview
  // the fullscreen offsets locally (Chrome devtools mobile view, etc.).
  if (typeof window !== "undefined" && typeof document !== "undefined") {
    try {
      const url = new URL(window.location.href);
      if (url.searchParams.get("tg-fullscreen") === "1") {
        setInsetVars(FULLSCREEN_TOP_FALLBACK_PX, 0);
      }
    } catch {
      /* malformed URL — ignore */
    }
  }

  const wa = getWebApp();
  if (!wa) return;
  try {
    wa.expand();
  } catch {
    /* very old clients */
  }
  // Paint the Telegram-owned chrome (strip behind close/back chip,
  // status-bar area, overscroll bounce) the same dark colour as the
  // app background so the user never sees a white flash when pulling
  // to refresh or when the WebView resizes. ``--background`` is HSL
  // ``228 35% 11%`` → ``#121927`` (also pinned in ``index.html``'s
  // ``theme-color``).
  const APP_BG = "#121927";
  if (typeof wa.setBackgroundColor === "function") {
    try {
      wa.setBackgroundColor(APP_BG);
    } catch {
      /* not supported */
    }
  }
  if (typeof wa.setHeaderColor === "function") {
    try {
      wa.setHeaderColor(APP_BG);
    } catch {
      /* not supported */
    }
  }
  // ``typeof === "function"`` is not enough here: telegram-web-app.js
  // defines these methods on EVERY client and logs
  // "Method … is not supported in version X" itself when called on an old
  // one — gate on the announced Bot API version instead.
  const versionAtLeast = (version: string): boolean => {
    try {
      return wa.isVersionAtLeast?.(version) ?? false;
    } catch {
      return false;
    }
  };
  let wentFullscreen = false;
  if (typeof wa.requestFullscreen === "function" && versionAtLeast("8.0")) {
    try {
      wa.requestFullscreen();
      wentFullscreen = true;
    } catch {
      /* not supported on this client */
    }
  }
  if (typeof wa.disableVerticalSwipes === "function" && versionAtLeast("7.7")) {
    try {
      wa.disableVerticalSwipes();
    } catch {
      /* not supported */
    }
  }
  // Telegram hydrates its own inset vars asynchronously — they're empty on
  // the first paint. Publish what the client already knows, then let the
  // subscription below correct it as values land and as the user rotates,
  // enters/leaves fullscreen, or the keyboard resizes the viewport.
  syncTelegramInsets({ assumeFullscreen: wentFullscreen });
  watchTelegramInsets();
}

/** Chip footprint to assume while the client hasn't reported insets yet. */
const FULLSCREEN_TOP_FALLBACK_PX = 56;

const INSET_EVENTS = [
  "safeAreaChanged",
  "contentSafeAreaChanged",
  "fullscreenChanged",
  "viewportChanged",
] as const;

function setInsetVars(top: number, bottom: number): void {
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.style.setProperty("--app-inset-top", `${String(Math.max(0, Math.round(top)))}px`);
  root.style.setProperty("--app-inset-bottom", `${String(Math.max(0, Math.round(bottom)))}px`);
}

export interface Inset {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

/**
 * Sum the device and Telegram-chrome insets into the offsets our layout uses.
 *
 * ``null`` means "this client reports nothing" — the caller then leaves the
 * CSS ``env()`` fallback in charge instead of writing a value.
 */
export function computeInsetPx(
  safe: Inset | undefined,
  content: Inset | undefined,
  fullscreen: boolean,
): { top: number; bottom: number } | null {
  if (!safe && !content) {
    // Pre-8.0 client. Only the chip needs guessing, and only in fullscreen —
    // env() has no idea Telegram is overlaying the top edge.
    return fullscreen ? { top: FULLSCREEN_TOP_FALLBACK_PX, bottom: 0 } : null;
  }
  const top = (safe?.top ?? 0) + (content?.top ?? 0);
  const bottom = (safe?.bottom ?? 0) + (content?.bottom ?? 0);
  return {
    // A fullscreen client reporting 0 up top hasn't measured the chip yet —
    // don't let the header slide under it in the meantime.
    top: fullscreen && top === 0 ? FULLSCREEN_TOP_FALLBACK_PX : top,
    bottom,
  };
}

/**
 * Publish the client's safe areas as ``--app-inset-top`` / ``--app-inset-bottom``.
 *
 * Two insets stack and both matter:
 *   - ``safeAreaInset`` — the device: notch / dynamic island, home indicator.
 *   - ``contentSafeAreaInset`` — Telegram's own chrome, i.e. the floating
 *     close/back chip that overlays the WebView in fullscreen.
 *
 * Content laid out against a screen edge has to clear their sum. Clients older
 * than Bot API 8.0 report neither; there we keep the CSS ``env()`` fallback and
 * only assume the chip footprint when we know fullscreen was granted.
 */
export function syncTelegramInsets({ assumeFullscreen = false } = {}): void {
  const wa = getWebApp();
  if (!wa) return;
  const next = computeInsetPx(
    wa.safeAreaInset,
    wa.contentSafeAreaInset,
    assumeFullscreen || wa.isFullscreen === true,
  );
  if (next) setInsetVars(next.top, next.bottom);
}

/** Keep the inset vars in step with rotation / fullscreen / viewport changes. */
export function watchTelegramInsets(): void {
  const wa = getWebApp();
  if (!wa || typeof wa.onEvent !== "function") return;
  const handler = () => {
    syncTelegramInsets();
  };
  for (const event of INSET_EVENTS) {
    try {
      wa.onEvent(event, handler);
    } catch {
      /* unknown event on this client — ignore */
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
export async function waitForInitData(timeoutMs = 2_000, stepMs = 50): Promise<string | null> {
  const start = Date.now();
  let initData = getWebApp()?.initData ?? "";
  while (!initData && Date.now() - start < timeoutMs) {
    await new Promise((r) => setTimeout(r, stepMs));
    initData = getWebApp()?.initData ?? "";
  }
  return initData || null;
}
