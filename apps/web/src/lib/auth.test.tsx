// @vitest-environment jsdom
import "@testing-library/jest-dom/vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "./auth";
import { clearTokens } from "./client";
import { listGuestOrders, saveGuestOrder } from "./guest-orders";

import type { ReactNode } from "react";

/**
 * Exercises `afterTokens` — the shared post-login/register-verify/telegram
 * funnel — through its `login`/`register` callers, against the real
 * `apiFetch`/`guest-orders` modules (only `fetch` and `localStorage` are
 * faked). Covers Task 6: claim-on-auth clears the device's guest order list,
 * a failed claim doesn't block sign-in, and `register` no longer opens a
 * session (the account needs email verification first).
 */

function jsonResponse(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>();

const ME = {
  id: "user-1",
  email: "buyer@example.com",
  locale: "ru",
  display_currency: "USD",
  display_name: null,
  photo_url: null,
  roles: [],
  created_at: "2026-07-01T00:00:00Z",
};

function renderAuth() {
  const qc = new QueryClient();
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={qc}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    );
  }
  return renderHook(() => useAuth(), { wrapper });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  window.localStorage.clear();
  clearTokens();
});

describe("afterTokens (via login)", () => {
  it("claims guest orders and clears the local list on success", async () => {
    saveGuestOrder({
      orderId: "o1",
      email: "Buyer@Example.com",
      brandSlug: "pubg",
      brandName: "PUBG Mobile",
      createdAt: "2026-07-01T00:00:00.000Z",
    });
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "tok1" })) // /auth/login
      .mockResolvedValueOnce(jsonResponse(200, ME)) // /auth/me
      .mockResolvedValueOnce(jsonResponse(200, { claimed: 1 })); // /orders/claim

    const { result } = renderAuth();
    await act(async () => {
      await result.current.login("buyer@example.com", "pw");
    });

    expect(listGuestOrders()).toEqual([]);
    expect(fetchMock.mock.calls.some(([url]) => url.includes("/orders/claim"))).toBe(true);
    await waitFor(() => {
      expect(result.current.user?.id).toBe("user-1");
    });
  });

  it("still signs the user in and clears local orders when the claim call fails", async () => {
    saveGuestOrder({
      orderId: "o1",
      email: "buyer@example.com",
      brandSlug: "pubg",
      brandName: "PUBG Mobile",
      createdAt: "2026-07-01T00:00:00.000Z",
    });
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, { access_token: "tok1" })) // /auth/login
      .mockResolvedValueOnce(jsonResponse(200, ME)) // /auth/me
      .mockResolvedValueOnce(jsonResponse(500, { type: "https://app.yupay.uz/errors/internal" })); // /orders/claim fails

    const { result } = renderAuth();
    // Must not throw — claim errors are swallowed as non-fatal.
    await act(async () => {
      await result.current.login("buyer@example.com", "pw");
    });

    expect(listGuestOrders()).toEqual([]);
    await waitFor(() => {
      expect(result.current.user?.id).toBe("user-1");
    });
  });
});

describe("register", () => {
  it("does not open a session — only calls /auth/register", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(201, { status: "verification_required", email: "new@example.com" }),
    );

    const { result } = renderAuth();
    await act(async () => {
      await result.current.register("new@example.com", "pw123456", "ru");
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const call = fetchMock.mock.calls[0];
    expect(call?.[0]).toContain("/auth/register");
    expect(result.current.user).toBeNull();
  });
});
