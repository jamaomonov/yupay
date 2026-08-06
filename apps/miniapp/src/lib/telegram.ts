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
  // Bot API 6.2+. Guards against a stray swipe-down closing the app.
  enableClosingConfirmation?: () => void;
  disableClosingConfirmation?: () => void;
  // Bot API 6.2+. Native dialogs — look like Telegram, not like a web modal.
  showConfirm?: (message: string, callback?: (confirmed: boolean) => void) => void;
  // Bot API 6.9+. Lets the bot message the user (order status, delivered codes).
  requestWriteAccess?: (callback?: (granted: boolean) => void) => void;
  // Bot API 7.0+. Native entry in the client's ⋮ menu.
  SettingsButton?: {
    isVisible: boolean;
    show: () => void;
    hide: () => void;
    onClick: (cb: () => void) => void;
    offClick: (cb: () => void) => void;
  };
  // Bot API 7.8+ / 8.0+. Sharing hooks.
  shareToStory?: (
    mediaUrl: string,
    params?: { text?: string; widget_link?: { url: string; name?: string } },
  ) => void;
  // Bot API 7.10+. On Android this also tints the system navigation bar.
  setBottomBarColor?: (color: string) => void;
  // Bot API 8.0+. Our layout is portrait-only.
  lockOrientation?: () => void;
  // Bot API 8.0+. `false` while the app is minimised — we pause polling on it.
  isActive?: boolean;
  // Bot API 6.1+. `viewportHeight` shrinks when the on-screen keyboard opens;
  // `viewportStableHeight` keeps the last settled value, so the difference
  // between them is the keyboard.
  viewportHeight?: number;
  viewportStableHeight?: number;
  // Bot API 8.0+. Home-screen shortcut. `checkHomeScreenStatus` answers
  // "unsupported" | "unknown" | "added" | "missed".
  addToHomeScreen?: () => void;
  checkHomeScreenStatus?: (callback?: (status: string) => void) => void;
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

/**
 * Tactile feedback.
 *
 * The cheapest signal that this is an app rather than a page — and it was
 * called exactly once in the whole Mini App (copying a Telegram id), so the
 * moments that actually carry meaning (choosing a pack, paying, a resolved
 * nickname, a delivered order) were silent. No-ops wherever the client doesn't
 * support it.
 */
export function haptic(kind: "select" | "press" | "ok" | "error"): void {
  const hf = getWebApp()?.HapticFeedback;
  if (!hf) return;
  try {
    if (kind === "select") hf.selectionChanged?.();
    else if (kind === "press") hf.impactOccurred?.("medium");
    else if (kind === "ok") hf.notificationOccurred?.("success");
    else hf.notificationOccurred?.("error");
  } catch {
    /* not supported */
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

/**
 * Whether this document was opened by a real Telegram client (as opposed to a
 * plain browser), knowable **synchronously even during the cold-launch race**
 * where ``WebApp.initData`` hasn't been populated yet.
 *
 * Unlike ``isInsideTelegram`` (which needs initData to be ready), this also
 * trusts the signed launch params the client puts in the URL fragment
 * (``tgWebAppData`` / ``tgWebAppPlatform``) and a concrete ``platform``. It is
 * the signal the bootstrap uses to GUARANTEE auth: opened-from-Telegram means
 * we must end up authenticated, never fall back to anonymous like a browser.
 */
export function launchedFromTelegram(): boolean {
  if (typeof window === "undefined") return false;
  const wa = getWebApp();
  if (wa?.initData && wa.initData.length > 0) return true;
  if (wa?.platform && wa.platform !== "" && wa.platform !== "unknown") return true;
  const params = `${window.location.hash} ${window.location.search}`;
  return params.includes("tgWebAppData") || params.includes("tgWebAppPlatform");
}

/**
 * Open an external URL — an acquirer's checkout / pay page — in a browser,
 * leaving the Mini App (and its BackButton route stack) alive underneath.
 *
 * Inside Telegram, ``openLink`` is a native bridge call that hands the URL to
 * the client to open in the system browser (or Telegram's in-app overlay,
 * depending on the client and the user's "in-app browser" setting). That is
 * deliberately different from ``window.location.href`` / ``<a target="_blank">``,
 * which the WebView treats as in-place navigation — the acquirer page *replaces*
 * the Mini App in the same WebView, losing the app and breaking the back arrow.
 * ``window.open`` is the dev / desktop fallback when there is no Telegram bridge.
 */
export function openExternalLink(url: string): void {
  const wa = getWebApp();
  if (wa && typeof wa.openLink === "function") {
    try {
      wa.openLink(url);
      return;
    } catch {
      /* fall through to the plain-browser fallback */
    }
  }
  if (typeof window !== "undefined") {
    window.open(url, "_blank", "noopener,noreferrer");
  }
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
  // The bottom bar completes the chrome we already paint — on Android it is
  // the system navigation bar, which would otherwise stay stock-black.
  if (typeof wa.setBottomBarColor === "function" && versionAtLeast("7.10")) {
    try {
      wa.setBottomBarColor(APP_BG);
    } catch {
      /* not supported */
    }
  }
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
  // The layout is portrait-only (max-w-430px column); a landscape flip just
  // stretches it. Pin the orientation the app launched in.
  if (typeof wa.lockOrientation === "function" && versionAtLeast("8.0")) {
    try {
      wa.lockOrientation();
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

/**
 * Telegram-owned chrome (strip behind the close/back chip, status-bar area,
 * overscroll bounce, Android nav bar) is painted the same colour as the app so
 * the user never sees a white flash on pull-to-refresh or a WebView resize.
 * ``--background`` is HSL ``228 35% 11%`` → also pinned as ``theme-color`` in
 * ``index.html``.
 */
const APP_BG = "#121927";

/**
 * Gate a call on the client's announced Bot API version.
 *
 * ``typeof wa.method === "function"`` is not enough: telegram-web-app.js
 * defines every method on every client and logs "Method … is not supported in
 * version X" itself when an old one is called.
 */
function versionAtLeast(version: string): boolean {
  const wa = getWebApp();
  if (!wa) return false;
  try {
    return wa.isVersionAtLeast?.(version) ?? false;
  } catch {
    return false;
  }
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

/**
 * Smallest drop in viewport height we'll read as "the keyboard came up".
 *
 * Soft keyboards are 250px and taller; the wobble from Telegram's own chrome
 * is far smaller. A floor in between keeps a stray resize from collapsing the
 * navigation under the customer's thumb.
 */
const KEYBOARD_MIN_PX = 120;

/** Is the on-screen keyboard eating the bottom of the viewport? */
export function computeKeyboardOpen(
  viewportHeight: number | undefined,
  stableHeight: number | undefined,
): boolean {
  if (typeof viewportHeight !== "number" || typeof stableHeight !== "number") return false;
  return stableHeight - viewportHeight >= KEYBOARD_MIN_PX;
}

export function isKeyboardOpen(): boolean {
  const wa = getWebApp();
  if (!wa) return false;
  return computeKeyboardOpen(wa.viewportHeight, wa.viewportStableHeight);
}

/**
 * Collapse the bottom-nav band while the keyboard is up.
 *
 * The nav is dead weight mid-typing and, on a phone with the keyboard open,
 * it and the pay button together eat most of what's left of the screen.
 * Zeroing `--app-nav-h` is enough: `--app-nav-total` is derived from it, so
 * the pay button drops and the content padding shrinks with no extra wiring.
 */
function syncKeyboardState(): void {
  if (typeof document === "undefined") return;
  document.documentElement.style.setProperty("--app-nav-h", isKeyboardOpen() ? "0px" : "56px");
}

/** Keep the inset vars in step with rotation / fullscreen / viewport changes. */
export function watchTelegramInsets(): void {
  const wa = getWebApp();
  if (!wa || typeof wa.onEvent !== "function") return;
  const handler = () => {
    syncTelegramInsets();
    syncKeyboardState();
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

// ---------------------------------------------------------------------------
// Closing confirmation
// ---------------------------------------------------------------------------

/**
 * Guard the app against a stray swipe-down / tap on ×.
 *
 * Kept scoped to the moments that actually matter — a payment in flight —
 * rather than switched on globally: a confirmation on every close would nag
 * users for whom nothing is at stake.
 */
export function setClosingConfirmation(enabled: boolean): void {
  const wa = getWebApp();
  if (!wa || !versionAtLeast("6.2")) return;
  try {
    if (enabled) wa.enableClosingConfirmation?.();
    else wa.disableClosingConfirmation?.();
  } catch {
    /* not supported */
  }
}

// ---------------------------------------------------------------------------
// Activity — pause background work while minimised
// ---------------------------------------------------------------------------

let appActive = true;

/**
 * ``false`` while the Mini App is minimised (Bot API 8.0+).
 *
 * Defaults to ``true`` everywhere else, so callers that gate polling on this
 * behave exactly as before on clients that never report activity.
 */
export function isAppActive(): boolean {
  return appActive;
}

/**
 * Track minimise/restore. ``onChange`` fires only on an actual transition;
 * returns an unsubscribe function.
 */
export function watchTelegramActivity(onChange?: (active: boolean) => void): () => void {
  const wa = getWebApp();
  if (!wa || typeof wa.onEvent !== "function") return () => undefined;
  const set = (next: boolean) => {
    if (appActive === next) return;
    appActive = next;
    onChange?.(next);
  };
  const onActivated = () => {
    set(true);
  };
  const onDeactivated = () => {
    set(false);
  };
  try {
    wa.onEvent("activated", onActivated);
    wa.onEvent("deactivated", onDeactivated);
  } catch {
    return () => undefined;
  }
  return () => {
    try {
      wa.offEvent?.("activated", onActivated);
      wa.offEvent?.("deactivated", onDeactivated);
    } catch {
      /* ignore */
    }
  };
}

// ---------------------------------------------------------------------------
// Native dialogs
// ---------------------------------------------------------------------------

/**
 * Native confirmation dialog.
 *
 * Resolves ``null`` when the client is too old to show one, so the caller can
 * decide: fall back to a web dialog, or just proceed.
 */
export async function confirmNatively(message: string): Promise<boolean | null> {
  const wa = getWebApp();
  if (!wa || typeof wa.showConfirm !== "function" || !versionAtLeast("6.2")) return null;
  return new Promise<boolean | null>((resolve) => {
    try {
      wa.showConfirm?.(message, (confirmed) => {
        resolve(confirmed);
      });
    } catch {
      resolve(null);
    }
  });
}

// ---------------------------------------------------------------------------
// Write access — so the bot may deliver order updates
// ---------------------------------------------------------------------------

/**
 * Ask permission for the bot to message the user (Bot API 6.9+).
 *
 * We deliver order status and voucher codes through the bot, so a customer who
 * opened the Mini App from a link and never pressed /start would otherwise
 * never hear back. Resolves ``null`` when the client can't ask.
 */
export async function requestWriteAccess(): Promise<boolean | null> {
  const wa = getWebApp();
  if (!wa || typeof wa.requestWriteAccess !== "function" || !versionAtLeast("6.9")) return null;
  return new Promise<boolean | null>((resolve) => {
    try {
      wa.requestWriteAccess?.((granted) => {
        resolve(granted);
      });
    } catch {
      resolve(null);
    }
  });
}

// ---------------------------------------------------------------------------
// Settings button — native entry in the client's ⋮ menu
// ---------------------------------------------------------------------------

/** Show the native Settings entry; returns a cleanup that hides it again. */
export function showSettingsButton(onClick: () => void): () => void {
  const wa = getWebApp();
  const button = wa?.SettingsButton;
  if (!button || !versionAtLeast("7.0")) return () => undefined;
  try {
    button.onClick(onClick);
    button.show();
  } catch {
    return () => undefined;
  }
  return () => {
    try {
      button.offClick(onClick);
      button.hide();
    } catch {
      /* ignore */
    }
  };
}

// ---------------------------------------------------------------------------
// Home screen shortcut
// ---------------------------------------------------------------------------

export type HomeScreenStatus = "unsupported" | "unknown" | "added" | "missed";

/**
 * Whether a home-screen shortcut is possible / already there (Bot API 8.0+).
 * ``null`` means the client can't tell us, so don't offer it.
 */
export async function getHomeScreenStatus(): Promise<HomeScreenStatus | null> {
  const wa = getWebApp();
  if (!wa || typeof wa.checkHomeScreenStatus !== "function" || !versionAtLeast("8.0")) return null;
  return new Promise<HomeScreenStatus | null>((resolve) => {
    // The event may never fire on a client that only pretends to support it.
    const timer = setTimeout(() => {
      resolve(null);
    }, 3_000);
    try {
      wa.checkHomeScreenStatus?.((status) => {
        clearTimeout(timer);
        resolve(status as HomeScreenStatus);
      });
    } catch {
      clearTimeout(timer);
      resolve(null);
    }
  });
}

/** Prompt to add the Mini App to the device home screen (Bot API 8.0+). */
export function addToHomeScreen(): void {
  const wa = getWebApp();
  if (!wa || typeof wa.addToHomeScreen !== "function" || !versionAtLeast("8.0")) return;
  try {
    wa.addToHomeScreen();
  } catch {
    /* not supported */
  }
}

// ---------------------------------------------------------------------------
// Sharing
// ---------------------------------------------------------------------------

/** Whether the client can open the native story composer (Bot API 7.8+). */
export function canShareToStory(): boolean {
  const wa = getWebApp();
  return Boolean(wa && typeof wa.shareToStory === "function" && versionAtLeast("7.8"));
}

/** Open the story composer with our media pre-loaded (Bot API 7.8+). */
export function shareToStory(
  mediaUrl: string,
  params?: { text?: string; widgetUrl?: string; widgetName?: string },
): void {
  const wa = getWebApp();
  if (!canShareToStory() || !wa) return;
  try {
    wa.shareToStory?.(mediaUrl, {
      ...(params?.text === undefined ? {} : { text: params.text }),
      ...(params?.widgetUrl === undefined
        ? {}
        : {
            widget_link: {
              url: params.widgetUrl,
              ...(params.widgetName === undefined ? {} : { name: params.widgetName }),
            },
          }),
    });
  } catch {
    /* not supported */
  }
}
