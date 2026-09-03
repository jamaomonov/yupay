import { afterEach, describe, expect, it, vi } from "vitest";

import { getGiftsHot, getGiftsPage, searchGifts } from "./gifts";

/**
 * Steam Gifts catalog data access.
 *
 * `getGiftsHot`/`getGiftsPage` are the server ISR fetchers behind
 * `/store/steam-gifts` and must never throw at build/render time: the whole
 * `/gifts/*` surface 404s while `steam_gifts_enabled` is off (see
 * `_ensure_enabled` in the API's `gifts/routes.py`), and the deployed API can
 * predate this feature entirely — the same "dark deploy" situation
 * `getBrandSlugs` in `lib/catalog.ts` already handles. `searchGifts` is the
 * client-side counterpart used by `GiftsBrowser` via TanStack Query, which
 * owns its own loading/error UI, so it is allowed to reject.
 */

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const HOT_ITEM = {
  app_id: 730,
  name: "Counter-Strike 2",
  image: "https://cdn.example/cs2.jpg",
  type: "game",
  price_usd: "9.99",
  price_uzs: "125000",
  discount_percent: 10,
  packages_count: 1,
  dlc_count: 0,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("getGiftsHot", () => {
  it("returns the hot items on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ items: [HOT_ITEM], total: 1 })),
    );
    await expect(getGiftsHot("ru")).resolves.toEqual([HOT_ITEM]);
  });

  it("returns [] on a 404 (dark deploy — the API predates the feature)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "not found" }, 404)));
    await expect(getGiftsHot("ru")).resolves.toEqual([]);
  });

  it("returns [] on a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    await expect(getGiftsHot("ru")).resolves.toEqual([]);
  });
});

describe("getGiftsPage", () => {
  it("returns the page on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ items: [HOT_ITEM], total: 42 })),
    );
    await expect(getGiftsPage("ru")).resolves.toEqual({ items: [HOT_ITEM], total: 42 });
  });

  it("returns the empty fallback on a 404", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "not found" }, 404)));
    await expect(getGiftsPage("ru")).resolves.toEqual({ items: [], total: 0 });
  });

  it("returns the empty fallback on a network error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("boom")));
    await expect(getGiftsPage("ru", 24)).resolves.toEqual({ items: [], total: 0 });
  });

  it("sends the requested offset", async () => {
    const fetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    await getGiftsPage("ru", 48);
    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url).searchParams.get("offset")).toBe("48");
  });
});

describe("searchGifts", () => {
  it("rejects instead of swallowing the error — the browser owns its own error UI", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "boom" }, 500)));
    await expect(searchGifts("ru", "dead", 0)).rejects.toThrow();
  });

  it("sends the search query, offset, and Accept-Language — with no bearer token", async () => {
    const fetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    await searchGifts("uz", "dead island", 24);
    const [url, init] = fetchMock.mock.calls[0]!;
    const parsed = new URL(url);
    expect(parsed.searchParams.get("search")).toBe("dead island");
    expect(parsed.searchParams.get("offset")).toBe("24");
    const headers = new Headers(init?.headers);
    expect(headers.get("Accept-Language")).toBe("uz");
    expect(headers.get("Authorization")).toBeNull();
  });

  it("omits the search param for an empty/whitespace query", async () => {
    const fetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(jsonResponse({ items: [], total: 0 }));
    vi.stubGlobal("fetch", fetchMock);
    await searchGifts("ru", "   ", 0);
    const [url] = fetchMock.mock.calls[0]!;
    expect(new URL(url).searchParams.has("search")).toBe(false);
  });
});
