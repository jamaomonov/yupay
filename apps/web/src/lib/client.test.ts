import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiFetch, clearTokens, getAccessToken, setTokens } from "./client";

/** Minimal localStorage backed by a Map — client.ts only needs get/set/remove. */
function fakeStorage() {
  const store = new Map<string, string>();
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();

beforeEach(() => {
  // client.ts guards on `typeof window` — give it a window with storage.
  vi.stubGlobal("window", { localStorage: fakeStorage() });
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiFetch", () => {
  it("attaches the stored access token as a Bearer header", async () => {
    setTokens("acc-1");
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }));

    await apiFetch("/orders");

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toContain("/api/v1/orders");
    expect(new Headers(init?.headers).get("Authorization")).toBe("Bearer acc-1");
    // The auth cookie must travel so the server can rotate/clear the refresh token.
    expect(init?.credentials).toBe("include");
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    setTokens("stale");
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, {})) // original request
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "fresh" }))
      .mockResolvedValueOnce(jsonResponse(200, { id: "o1" })); // retry

    const out = await apiFetch<{ id: string }>("/orders/o1");

    expect(out.id).toBe("o1");
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const refreshCall = fetchMock.mock.calls[1]!;
    expect(refreshCall[0]).toContain("/api/v1/auth/refresh");
    // The refresh token rides the HttpOnly cookie, so the call carries no body and
    // must include credentials for the cookie to be sent and the rotated one stored.
    expect(refreshCall[1]?.body).toBeUndefined();
    expect(refreshCall[1]?.credentials).toBe("include");
    const retryCall = fetchMock.mock.calls[2]!;
    expect(new Headers(retryCall[1]?.headers).get("Authorization")).toBe("Bearer fresh");
    expect(getAccessToken()).toBe("fresh");
  });

  it("clears tokens and throws when the refresh itself fails", async () => {
    setTokens("stale");
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(jsonResponse(401, {})); // refresh rejected

    await expect(apiFetch("/orders")).rejects.toBeInstanceOf(ApiError);
    expect(getAccessToken()).toBeNull();
  });

  it("does not loop when the retried request 401s again", async () => {
    setTokens("stale");
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, {}))
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "fresh" }))
      .mockResolvedValueOnce(jsonResponse(401, {})); // still unauthorized

    await expect(apiFetch("/orders")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(3); // no second refresh attempt
  });

  it("never sends Authorization for anonymous calls", async () => {
    setTokens("acc-1");
    fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));

    await apiFetch("/catalog/brands", { anonymous: true });

    const [, init] = fetchMock.mock.calls[0]!;
    expect(new Headers(init?.headers).get("Authorization")).toBeNull();
    clearTokens();
  });
});
