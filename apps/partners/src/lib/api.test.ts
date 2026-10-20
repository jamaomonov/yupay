// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, clearTokens, hasSession, setAccessToken } from "./api";

/**
 * The refresh behaviour, which is the only part of this file with a decision
 * in it. Everything else is a fetch with headers.
 *
 * Two properties. Refresh **once** per call, never in a loop: each refresh
 * rotates the cookie, so a loop would turn one expired session into a stream
 * of invalidated ones while hammering the API. And every request carries
 * credentials, because the refresh cookie *is* the session — a call that omits
 * it cannot be refreshed.
 */

function respond(status: number, body: unknown = {}): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  } as unknown as Response;
}

beforeEach(() => {
  clearTokens();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("api", () => {
  it("refreshes once on a 401 and replays the request", async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn((url: string) => {
      calls.push(url);
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(respond(200, { access_token: "a2", refresh_token: "r2" }));
      }
      // First protected call fails, the replay succeeds.
      return Promise.resolve(
        calls.filter((c) => c.endsWith("/me")).length === 1
          ? respond(401)
          : respond(200, { id: "p-1" }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("a1");

    const me = await api<{ id: string }>("/api/v1/affiliate/me");

    expect(me).toEqual({ id: "p-1" });
    expect(calls.filter((c) => c.endsWith("/auth/refresh"))).toHaveLength(1);
    expect(calls.filter((c) => c.endsWith("/me"))).toHaveLength(2);
  });

  it("gives up after one refresh rather than looping", async () => {
    const calls: string[] = [];
    const fetchMock = vi.fn((url: string) => {
      calls.push(url);
      if (url.endsWith("/auth/refresh")) {
        return Promise.resolve(respond(200, { access_token: "a2", refresh_token: "r2" }));
      }
      return Promise.resolve(respond(401));
    });
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("a1");

    await expect(api("/api/v1/affiliate/me")).rejects.toBeInstanceOf(ApiError);

    expect(calls.filter((c) => c.endsWith("/auth/refresh"))).toHaveLength(1);
    expect(calls.filter((c) => c.endsWith("/me"))).toHaveLength(2);
    // The session is gone; the caller must be told to sign in again rather
    // than left holding a token that will 401 forever.
    expect(hasSession()).toBe(false);
  });

  it("does not try to refresh when the refresh itself is refused", async () => {
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(url.endsWith("/auth/refresh") ? respond(401) : respond(401)),
    );
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("a1");

    await expect(api("/api/v1/affiliate/me")).rejects.toBeInstanceOf(ApiError);
    expect(hasSession()).toBe(false);
  });

  it("always sends credentials, because the refresh cookie is the session", async () => {
    let sentCredentials: RequestCredentials | undefined;
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      sentCredentials = init.credentials;
      return Promise.resolve(respond(200, {}));
    });
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("a1");

    await api("/api/v1/affiliate/me");
    expect(sentCredentials).toBe("include");
  });

  it("never sends an Authorization header on an anonymous call", async () => {
    let sentAuth: string | null = "unset";
    const fetchMock = vi.fn((_url: string, init: RequestInit) => {
      sentAuth = new Headers(init.headers).get("Authorization");
      return Promise.resolve(respond(200, {}));
    });
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("a1");

    await api("/api/v1/affiliate/auth/login", { method: "POST", body: {}, anonymous: true });
    expect(sentAuth).toBeNull();
  });
});

describe("concurrent 401s", () => {
  it("share one refresh instead of spending the rotating cookie once each", async () => {
    let refreshes = 0;
    let fresh = false;
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith("/auth/refresh")) {
        refreshes += 1;
        // A second presentation of the rotated cookie is refused.
        if (refreshes > 1) return Promise.resolve(respond(401));
        fresh = true;
        return Promise.resolve(respond(200, { access_token: "a2" }));
      }
      return Promise.resolve(respond(fresh ? 200 : 401, { ok: true }));
    });
    vi.stubGlobal("fetch", fetchMock);
    setAccessToken("stale");

    const results = await Promise.all(
      ["/a", "/b", "/c", "/d", "/e"].map((p) => api<{ ok: boolean }>(p)),
    );

    expect(refreshes).toBe(1);
    expect(results.every((r) => r.ok)).toBe(true);
    expect(hasSession()).toBe(true);
  });
});
