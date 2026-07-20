/**
 * Version gating for the optional WebApp APIs.
 *
 * telegram-web-app.js defines every method on every client and logs "Method …
 * is not supported in version X" itself when an old one is called, so mere
 * existence checks aren't enough — each call has to be gated on the announced
 * Bot API version. These tests pin that: on an old client nothing fires, on a
 * new one everything does.
 */

import { afterEach, describe, expect, test, vi } from "vitest";

import {
  addToHomeScreen,
  canShareToStory,
  confirmNatively,
  getHomeScreenStatus,
  requestWriteAccess,
  setClosingConfirmation,
  shareToStory,
  showSettingsButton,
} from "./telegram";

interface Spies {
  enableClosingConfirmation: ReturnType<typeof vi.fn>;
  disableClosingConfirmation: ReturnType<typeof vi.fn>;
  showConfirm: ReturnType<typeof vi.fn>;
  requestWriteAccess: ReturnType<typeof vi.fn>;
  addToHomeScreen: ReturnType<typeof vi.fn>;
  checkHomeScreenStatus: ReturnType<typeof vi.fn>;
  shareToStory: ReturnType<typeof vi.fn>;
  settingsShow: ReturnType<typeof vi.fn>;
  settingsOnClick: ReturnType<typeof vi.fn>;
}

/** Install a fake Telegram client announcing `version`. */
function fakeClient(version: string): Spies {
  const spies: Spies = {
    enableClosingConfirmation: vi.fn(),
    disableClosingConfirmation: vi.fn(),
    showConfirm: vi.fn((_msg: string, cb?: (ok: boolean) => void) => {
      cb?.(true);
    }),
    requestWriteAccess: vi.fn((cb?: (granted: boolean) => void) => {
      cb?.(true);
    }),
    addToHomeScreen: vi.fn(),
    checkHomeScreenStatus: vi.fn((cb?: (status: string) => void) => {
      cb?.("missed");
    }),
    shareToStory: vi.fn(),
    settingsShow: vi.fn(),
    settingsOnClick: vi.fn(),
  };
  const parse = (v: string) => v.split(".").map(Number);
  (globalThis as { window?: unknown }).window = {
    Telegram: {
      WebApp: {
        isVersionAtLeast: (want: string) => {
          const [wantMajor = 0, wantMinor = 0] = parse(want);
          const [major = 0, minor = 0] = parse(version);
          return major > wantMajor || (major === wantMajor && minor >= wantMinor);
        },
        enableClosingConfirmation: spies.enableClosingConfirmation,
        disableClosingConfirmation: spies.disableClosingConfirmation,
        showConfirm: spies.showConfirm,
        requestWriteAccess: spies.requestWriteAccess,
        addToHomeScreen: spies.addToHomeScreen,
        checkHomeScreenStatus: spies.checkHomeScreenStatus,
        shareToStory: spies.shareToStory,
        SettingsButton: {
          isVisible: false,
          show: spies.settingsShow,
          hide: vi.fn(),
          onClick: spies.settingsOnClick,
          offClick: vi.fn(),
        },
      },
    },
  };
  return spies;
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
});

describe("on a current client (8.0)", () => {
  test("closing confirmation toggles both ways", () => {
    const s = fakeClient("8.0");
    setClosingConfirmation(true);
    expect(s.enableClosingConfirmation).toHaveBeenCalled();
    setClosingConfirmation(false);
    expect(s.disableClosingConfirmation).toHaveBeenCalled();
  });

  test("native confirm resolves the user's answer", async () => {
    fakeClient("8.0");
    await expect(confirmNatively("Выйти?")).resolves.toBe(true);
  });

  test("write access resolves the grant", async () => {
    fakeClient("8.0");
    await expect(requestWriteAccess()).resolves.toBe(true);
  });

  test("home screen status is reported and the prompt fires", async () => {
    const s = fakeClient("8.0");
    await expect(getHomeScreenStatus()).resolves.toBe("missed");
    addToHomeScreen();
    expect(s.addToHomeScreen).toHaveBeenCalled();
  });

  test("story sharing passes media and text through", () => {
    const s = fakeClient("8.0");
    expect(canShareToStory()).toBe(true);
    shareToStory("https://cdn.yupay.uz/hero.jpg", { text: "PUBG" });
    expect(s.shareToStory).toHaveBeenCalledWith("https://cdn.yupay.uz/hero.jpg", { text: "PUBG" });
  });

  test("settings button shows and its cleanup unsubscribes", () => {
    const s = fakeClient("8.0");
    const cleanup = showSettingsButton(() => undefined);
    expect(s.settingsShow).toHaveBeenCalled();
    expect(s.settingsOnClick).toHaveBeenCalled();
    expect(() => {
      cleanup();
    }).not.toThrow();
  });
});

describe("on a legacy client (6.0)", () => {
  test("nothing newer than 6.0 is invoked", async () => {
    const s = fakeClient("6.0");

    setClosingConfirmation(true); // 6.2+
    expect(s.enableClosingConfirmation).not.toHaveBeenCalled();

    addToHomeScreen(); // 8.0+
    expect(s.addToHomeScreen).not.toHaveBeenCalled();

    shareToStory("https://cdn.yupay.uz/hero.jpg"); // 7.8+
    expect(s.shareToStory).not.toHaveBeenCalled();
    expect(canShareToStory()).toBe(false);

    showSettingsButton(() => undefined); // 7.0+
    expect(s.settingsShow).not.toHaveBeenCalled();

    // Unsupported dialogs resolve null so callers can fall back rather than
    // hang waiting for a callback that will never come.
    await expect(confirmNatively("Выйти?")).resolves.toBeNull();
    await expect(requestWriteAccess()).resolves.toBeNull();
    await expect(getHomeScreenStatus()).resolves.toBeNull();
  });
});

describe("outside Telegram", () => {
  test("every helper is inert instead of throwing", async () => {
    expect(() => {
      setClosingConfirmation(true);
      addToHomeScreen();
      shareToStory("https://cdn.yupay.uz/hero.jpg");
    }).not.toThrow();
    expect(canShareToStory()).toBe(false);
    await expect(confirmNatively("?")).resolves.toBeNull();
    await expect(requestWriteAccess()).resolves.toBeNull();
  });
});
