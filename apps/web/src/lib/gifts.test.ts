import { afterEach, describe, expect, it, vi } from "vitest";

import {
  checkGiftProfile,
  getGiftsHot,
  getGiftsPage,
  profileCheckBlocks,
  searchGifts,
} from "./gifts";

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

/**
 * The pre-purchase recipient check (`POST /gifts/steam-profile`).
 *
 * The one rule the whole feature turns on: only a definitive `not_found` —
 * Steam itself saying the profile does not exist — may stand between the
 * buyer and Pay. Everything else (`unsupported`, `unavailable`, a thrown
 * fetch, a 500, a link never checked at all) has to leave the purchase
 * available, because a check that fails on our side must never cost a sale.
 */
describe("checkGiftProfile", () => {
  it("narrows a found verdict to the nickname and avatar the card renders", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: "found",
          steam_id: "76561198000000000",
          nickname: "Neo",
          avatar_url: "https://avatars.steamstatic.com/abc_full.jpg",
        }),
      ),
    );
    await expect(checkGiftProfile("https://steamcommunity.com/id/neo")).resolves.toEqual({
      status: "found",
      nickname: "Neo",
      avatarUrl: "https://avatars.steamstatic.com/abc_full.jpg",
    });
  });

  it("keeps a found verdict that has no avatar — the nickname alone still confirms", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: "found",
          steam_id: "76561198000000000",
          nickname: "Neo",
          avatar_url: null,
        }),
      ),
    );
    await expect(checkGiftProfile("https://steamcommunity.com/id/neo")).resolves.toEqual({
      status: "found",
      nickname: "Neo",
      avatarUrl: null,
    });
  });

  it.each(["not_found", "unsupported", "unavailable"] as const)(
    "passes a %s verdict straight through",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            jsonResponse({ status, steam_id: null, nickname: null, avatar_url: null }),
          ),
      );
      await expect(checkGiftProfile("https://steamcommunity.com/id/ghost")).resolves.toEqual({
        status,
      });
    },
  );

  it("degrades a nameless found verdict to unavailable rather than an empty card", async () => {
    // The API contract says this cannot happen: `found` is only returned once
    // Steam actually gave us a persona. If it ever did, a green confirmation
    // pill wrapped around nothing is the worst possible answer — and blocking
    // would be worse still, so it lands on the non-blocking status.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse({
          status: "found",
          steam_id: "76561198000000000",
          nickname: null,
          avatar_url: "https://avatars.steamstatic.com/abc_full.jpg",
        }),
      ),
    );
    await expect(checkGiftProfile("https://steamcommunity.com/id/neo")).resolves.toEqual({
      status: "unavailable",
    });
  });

  it("folds a network error into unavailable — never into a blocking verdict", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    await expect(checkGiftProfile("https://steamcommunity.com/id/neo")).resolves.toEqual({
      status: "unavailable",
    });
  });

  it("folds our own 500 into unavailable too", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ detail: "boom" }, 500)));
    await expect(checkGiftProfile("https://steamcommunity.com/id/neo")).resolves.toEqual({
      status: "unavailable",
    });
  });

  it("posts the link in the body, never in a query string, and sends no bearer token", async () => {
    // The query string is what Caddy's access log records verbatim and ships
    // to Loki, so a GET here would park a *third party's* Steam identity in
    // our logs. The body is not logged; this test is the client-side half of
    // `test_a_get_with_the_link_in_the_query_string_is_405` on the API.
    const fetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(
        jsonResponse({ status: "unavailable", steam_id: null, nickname: null, avatar_url: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await checkGiftProfile("https://steamcommunity.com/id/neo mad");
    const [url, init] = fetchMock.mock.calls[0]!;
    const parsed = new URL(url);
    expect(parsed.pathname).toBe("/api/v1/gifts/steam-profile");
    expect(parsed.search).toBe("");
    expect(init?.method).toBe("POST");
    const raw = init?.body;
    // Narrowed rather than cast: `BodyInit` also covers Blob/FormData/streams,
    // none of which `JSON.parse` would take.
    if (typeof raw !== "string") throw new Error("expected a JSON string body");
    const body: unknown = JSON.parse(raw);
    expect(body).toEqual({ invite_url: "https://steamcommunity.com/id/neo mad" });
    expect(new Headers(init?.headers).get("Authorization")).toBeNull();
  });

  it("carries an abort signal so a hung request can't spin the button forever", async () => {
    const fetchMock = vi
      .fn<(url: string, init?: RequestInit) => Promise<Response>>()
      .mockResolvedValue(
        jsonResponse({ status: "unavailable", steam_id: null, nickname: null, avatar_url: null }),
      );
    vi.stubGlobal("fetch", fetchMock);
    await checkGiftProfile("https://steamcommunity.com/id/neo");
    const [, init] = fetchMock.mock.calls[0]!;
    expect(init?.signal).toBeInstanceOf(AbortSignal);
  });

  it("folds the abort itself into unavailable, like any other failure", async () => {
    // What the browser actually does when the signal fires: reject the fetch.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new DOMException("The operation was aborted.", "TimeoutError")),
    );
    await expect(checkGiftProfile("https://steamcommunity.com/id/neo")).resolves.toEqual({
      status: "unavailable",
    });
  });
});

describe("profileCheckBlocks", () => {
  it("blocks only on a definitive not_found", () => {
    expect(profileCheckBlocks({ status: "not_found" })).toBe(true);
  });

  it.each(["unsupported", "unavailable"] as const)(
    "does not block on %s — that failure is ours, not the recipient's",
    (status) => {
      expect(profileCheckBlocks({ status })).toBe(false);
    },
  );

  it("does not block a found verdict", () => {
    expect(profileCheckBlocks({ status: "found", nickname: "Neo", avatarUrl: null })).toBe(false);
  });

  it("does not block a link nobody checked — the check is advisory, not required", () => {
    // Deliberately the opposite of `blocksCheckout` in `player-check-state.ts`,
    // where an unchecked id does block: there the check is a gate, here it is
    // a second pair of eyes the buyer may skip.
    expect(profileCheckBlocks(null)).toBe(false);
  });
});
