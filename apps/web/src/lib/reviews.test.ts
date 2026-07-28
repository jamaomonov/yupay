// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { getReviewEligibility, submitReview } from "./reviews";

// Under vitest's default "node" environment `window` is undefined, so
// `getAccessToken()` always returns null and these tests can't tell "no
// Bearer" apart from "no token to begin with". jsdom gives us a real
// `window.localStorage` so we can plant a stale Bearer token and prove that
// the guest path (`anonymous: true`) suppresses it in favor of `Guest <token>`.
const ACCESS_KEY = "yupay.web.access_token";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("getReviewEligibility (guest)", () => {
  it("sends Guest auth + X-Guest-Email and no Bearer, even with a stale access token in storage", async () => {
    window.localStorage.setItem(ACCESS_KEY, "stale-bearer-token");
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();
    vi.stubGlobal("fetch", fetchMock);
    // mintGuestToken hits /auth/guest first:
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ access_token: "gt" }), { status: 200 }),
    );
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ brand_slug: "steam", delivered: true, already_reviewed: false }),
        { status: 200 },
      ),
    );
    const res = await getReviewEligibility("ord-1", { guestEmail: "G@x.com " });
    expect(res.brand_slug).toBe("steam");
    const headers = new Headers(fetchMock.mock.calls[1]?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Guest gt");
    expect(headers.get("Authorization")).not.toMatch(/^Bearer/);
    expect(headers.get("X-Guest-Email")).toBe("g@x.com");
  });
});

describe("submitReview (guest)", () => {
  it("sends Guest auth and no Bearer, even with a stale access token in storage", async () => {
    window.localStorage.setItem(ACCESS_KEY, "stale-bearer-token");
    const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();
    vi.stubGlobal("fetch", fetchMock);
    // mintGuestToken hits /auth/guest first:
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ access_token: "gt2" }), { status: 200 }),
    );
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({
          id: "r1",
          rating: 5,
          body: null,
          author_name: null,
          created_at: "2026-01-01T00:00:00Z",
        }),
        { status: 200 },
      ),
    );
    await submitReview(
      { order_id: "ord-1", brand_slug: "steam", rating: 5 },
      { guestEmail: "g@x.com" },
    );
    const headers = new Headers(fetchMock.mock.calls[1]?.[1]?.headers);
    expect(headers.get("Authorization")).toBe("Guest gt2");
    expect(headers.get("Authorization")).not.toMatch(/^Bearer/);
  });
});
