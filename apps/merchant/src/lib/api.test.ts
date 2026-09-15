import { LOCALES } from "@yupay/i18n";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api, loginPathFor } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

/**
 * Where a lapsed session lands.
 *
 * The cabinet's screens each render an *empty state* when their read fails,
 * so a session that cannot be rotated used to look like "your account is
 * broken" rather than "you are signed out". The redirect is what fixes that,
 * and the only part of it with a decision in it is the locale.
 */
describe("loginPathFor", () => {
  it("keeps the locale the reader is actually in", () => {
    expect(loginPathFor("/en/cabinet/orders")).toBe("/en/login");
    expect(loginPathFor("/uz/cabinet/settings")).toBe("/uz/login");
  });

  it("adds no prefix for the default locale, which has no segment", () => {
    // `localePrefix: "as-needed"`: `/cabinet` is already Russian, and
    // `/ru/login` would be a second URL for the same form.
    expect(loginPathFor("/cabinet")).toBe("/login");
    expect(loginPathFor("/")).toBe("/login");
  });

  it("treats an unrecognised first segment as a path, not a locale", () => {
    // The failure this guards: a future top-level route whose name is two
    // letters would otherwise be read as a locale and lose the redirect.
    expect(loginPathFor("/cabinet/orders")).toBe("/login");
    expect(loginPathFor("/de/cabinet")).toBe("/login");
  });

  it("covers every locale the app actually ships", () => {
    // Pinned to the catalog rather than to a literal list: a fourth locale
    // must not quietly stop redirecting.
    for (const locale of LOCALES) {
      expect(loginPathFor(`/${locale}/cabinet`)).toBe(`/${locale}/login`);
    }
  });
});

/**
 * Two requests that 401 at the same moment.
 *
 * The cabinet shell produces exactly this on every load: the profile and the
 * catalog go out together. Refresh tokens rotate, so if both started a
 * rotation the second would present a token the first had already spent — and
 * a valid session would be signed out on a cold load.
 */
describe("concurrent rotation", () => {
  it("rotates once for every request that hit 401 together", async () => {
    const store = new Map<string, string>([
      ["yupay.merchant.access", "stale"],
      ["yupay.merchant.refresh", "good"],
    ]);
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => store.set(key, value),
        removeItem: (key: string) => store.delete(key),
      },
      location: { pathname: "/en/cabinet", assign: vi.fn() },
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    });

    let refreshes = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/refresh")) {
        refreshes += 1;
        // Slow enough that the second caller is certainly still waiting.
        await new Promise((resolve) => setTimeout(resolve, 20));
        store.set("yupay.merchant.access", "fresh");
        return response(200, { access_token: "fresh", refresh_token: "next", expires_in: 900 });
      }
      const token = store.get("yupay.merchant.access");
      return token === "fresh" ? response(200, { ok: true }) : response(401, {});
    });
    vi.stubGlobal("fetch", fetchMock);

    const [first, second] = await Promise.all([api("/me"), api("/catalog")]);

    expect(refreshes).toBe(1);
    expect(first).toEqual({ ok: true });
    expect(second).toEqual({ ok: true });
  });
});

function response(status: number, body: unknown): Response {
  return {
    status,
    ok: status < 400,
    text: async () => JSON.stringify(body),
    json: async () => body,
    headers: new Map<string, string>() as unknown as Headers,
  } as unknown as Response;
}
