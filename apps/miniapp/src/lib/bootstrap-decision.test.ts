import { afterEach, describe, expect, test, vi } from "vitest";

import { decideBoot } from "./auth";
import { launchedFromTelegram } from "./telegram";

describe("decideBoot", () => {
  test("authenticated → ready, regardless of context", () => {
    expect(decideBoot(true, true)).toBe("ready");
    expect(decideBoot(true, false)).toBe("ready");
  });

  test("inside Telegram but not authenticated → retry, NEVER anonymous", () => {
    // This is the guarantee: a Telegram user must never land on the app signed
    // out. The gate keeps retrying behind the splash instead of releasing.
    expect(decideBoot(false, true)).toBe("retry");
  });

  test("plain browser (dev) and not authenticated → anonymous fallback", () => {
    expect(decideBoot(false, false)).toBe("anonymous");
  });
});

describe("launchedFromTelegram", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("true when initData is already populated", () => {
    vi.stubGlobal("window", {
      Telegram: { WebApp: { initData: "user=%7B...%7D&hash=abc", platform: "android" } },
      location: { hash: "", search: "" },
    });
    expect(launchedFromTelegram()).toBe(true);
  });

  test("true on a cold launch: initData empty but launch params in the URL hash", () => {
    // The Android race — telegram-web-app.js hasn't populated WebApp.initData
    // yet, but the client already put the signed params in the fragment.
    vi.stubGlobal("window", {
      Telegram: { WebApp: { initData: "", platform: "unknown" } },
      location: {
        hash: "#tgWebAppData=abc&tgWebAppVersion=8.0&tgWebAppPlatform=android",
        search: "",
      },
    });
    expect(launchedFromTelegram()).toBe(true);
  });

  test("true when the client set a real platform even before initData", () => {
    vi.stubGlobal("window", {
      Telegram: { WebApp: { initData: "", platform: "ios" } },
      location: { hash: "", search: "" },
    });
    expect(launchedFromTelegram()).toBe(true);
  });

  test("false in a plain browser: no params, no initData, unknown platform", () => {
    vi.stubGlobal("window", {
      Telegram: { WebApp: { initData: "", platform: "unknown" } },
      location: { hash: "", search: "" },
    });
    expect(launchedFromTelegram()).toBe(false);
  });

  test("false when Telegram bridge is absent entirely", () => {
    vi.stubGlobal("window", { location: { hash: "", search: "" } });
    expect(launchedFromTelegram()).toBe(false);
  });
});
