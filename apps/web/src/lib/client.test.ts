import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  apiFetch,
  clearTokens,
  getAccessToken,
  hasSessionHint,
  setTokens,
} from "./client";

/** Minimal localStorage backed by a Map — client.ts only needs get/set/remove. */
function fakeStorage() {
  const store = new Map<string, string>();
  return {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  };
}

describe("access token storage (in-memory, XSS-safe)", () => {
  const store = new Map<string, string>();
  beforeEach(() => {
    store.clear();
    vi.stubGlobal("window", {
      localStorage: {
        getItem: (k: string) => store.get(k) ?? null,
        setItem: (k: string, v: string) => void store.set(k, v),
        removeItem: (k: string) => void store.delete(k),
      },
    });
  });
  afterEach(() => {
    clearTokens();
    vi.unstubAllGlobals();
  });

  it("keeps the access token in memory, never in web storage", () => {
    setTokens("secret-access-jwt");
    expect(getAccessToken()).toBe("secret-access-jwt");
    // An XSS payload reading localStorage must not find the token anywhere.
    expect([...store.values()].join("|")).not.toContain("secret-access-jwt");
    expect(store.get("yupay.web.access_token")).toBeUndefined();
  });

  it("records only a non-secret session hint in localStorage", () => {
    setTokens("secret-access-jwt");
    expect(hasSessionHint()).toBe(true);
    expect(store.get("yupay.web.has_session")).toBe("1");
  });

  it("clearTokens drops both the in-memory token and the hint", () => {
    setTokens("secret-access-jwt");
    clearTokens();
    expect(getAccessToken()).toBeNull();
    expect(hasSessionHint()).toBe(false);
  });

  it("purges a legacy localStorage-stored access token on set", () => {
    store.set("yupay.web.access_token", "legacy-token");
    setTokens("new-jwt");
    expect(store.get("yupay.web.access_token")).toBeUndefined();
  });
});

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

  it("surfaces the RFC 7807 `type` from a problem+json error body on ApiError", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(403, {
        type: "https://app.yupay.uz/errors/email-unverified",
        title: "Email not verified",
        status: 403,
        detail: "Confirm your email address before signing in.",
      }),
    );

    await expect(apiFetch("/auth/login", { anonymous: true })).rejects.toMatchObject({
      status: 403,
      type: "https://app.yupay.uz/errors/email-unverified",
    });
  });

  it("leaves ApiError.type undefined for a non-JSON or typeless error body", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("not json", { status: 500, headers: { "Content-Type": "text/plain" } }),
    );

    const err = await apiFetch("/orders", { anonymous: true }).catch((e: unknown) => e);
    expect(err).toMatchObject({ status: 500, type: undefined });
  });
});
