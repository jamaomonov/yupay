import { afterEach, describe, expect, it, vi } from "vitest";

import { getReviewEligibility } from "./reviews";

afterEach(() => vi.restoreAllMocks());

describe("getReviewEligibility (guest)", () => {
  it("sends Guest auth + X-Guest-Email and no Bearer", async () => {
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
    expect(headers.get("X-Guest-Email")).toBe("g@x.com");
  });
});
