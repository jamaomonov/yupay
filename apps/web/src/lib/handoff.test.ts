import { beforeEach, describe, expect, it, vi } from "vitest";

import { stashHandoff, takeHandoff } from "./handoff";

function fakeStorage() {
  const store = new Map<string, string>();
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
}

beforeEach(() => {
  vi.stubGlobal("window", { sessionStorage: fakeStorage() });
});

describe("handoff", () => {
  it("hands the fields to the page they are for, once", () => {
    stashHandoff("/store/steam", new URLSearchParams({ steam_login: "gaben", amount: "5" }));
    expect(takeHandoff("/store/steam/")?.get("steam_login")).toBe("gaben");
    expect(takeHandoff("/store/steam")).toBeNull();
  });

  it("never hands them to another page", () => {
    stashHandoff("/store/steam", new URLSearchParams({ steam_login: "gaben" }));
    expect(takeHandoff("/store/telegram-stars")).toBeNull();
  });

  it("ignores garbage", () => {
    window.sessionStorage.setItem("yupay.web.handoff", "{oops");
    expect(takeHandoff("/store/steam")).toBeNull();
  });
});
