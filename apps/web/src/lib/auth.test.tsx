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

it("leaves nothing of the previous account in the cache after logout", async () => {
  // Shared device: A signs out, B signs in without a reload, so the same
  // QueryClient lives on. TanStack serves cached data while it refetches —
  // which for the wallet is one customer seeing another's balance and their
  // whole ledger history.
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(["wallet"], { balances: [{ balance: "999999" }] });
  qc.setQueryData(["wallet", "transactions"], { items: [{ id: "tx-a" }] });
  qc.setQueryData(["orders"], { items: [{ id: "order-a" }] });

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
  const { result } = renderHook(() => useAuth(), { wrapper });

  await act(async () => {
    result.current.logout();
  });

  expect(qc.getQueryData(["wallet"])).toBeUndefined();
  expect(qc.getQueryData(["wallet", "transactions"])).toBeUndefined();
  expect(qc.getQueryData(["orders"])).toBeUndefined();
});

it("signs the user out of the UI, not just the cache", async () => {
  // The reported bug: pressing "Выйти" changed nothing on screen until the
  // page was reloaded. The sibling test above proves the cache is emptied —
  // but every auth-gated component reads `user`, and that is what stayed put,
  // so the header kept showing the account that had just left.
  fetchMock
    .mockResolvedValueOnce(jsonResponse(200, { access_token: "tok1" })) // /auth/login
    .mockResolvedValueOnce(jsonResponse(200, ME)) // /auth/me
    .mockResolvedValueOnce(jsonResponse(200, { claimed: 0 })) // /orders/claim
    .mockResolvedValue(jsonResponse(204, null)); // /auth/logout

  const { result } = renderAuth();
  await act(async () => {
    await result.current.login("buyer@example.com", "pw");
  });
  await waitFor(() => {
    expect(result.current.user?.id).toBe("user-1");
  });

  await act(async () => {
    result.current.logout();
  });

  // `waitFor`, not a bare assertion: TanStack notifies through its scheduler,
  // so the re-render lands a tick after the cache write. Asserting straight
  // after `act` reads the previous render and fails on working code.
  await waitFor(() => {
    expect(result.current.user).toBeNull();
  });
});

it("recovers when the post-login `me` fetch fails, instead of stranding a real session", async () => {
  // The reported bug: signing in appeared to do nothing until the page was
  // reloaded. `setTokens` had already run — the session was real and the
  // refresh cookie was set, which is why a reload fixed it — but a failure
  // anywhere after it aborted `afterTokens`, so the user record was never
  // cached and nothing re-rendered. `TelegramLoginButton` calls this as
  // `void loginWithTelegram(u)`, so the rejection was swallowed in silence.
  let meCalls = 0;
  fetchMock.mockImplementation((url: string) => {
    if (url.includes("/auth/telegram/widget")) {
      return Promise.resolve(jsonResponse(200, { access_token: "tok" }));
    }
    if (url.includes("/auth/me")) {
      meCalls += 1;
      // The first call — the one inside `afterTokens` — fails.
      if (meCalls === 1) return Promise.resolve(jsonResponse(500, { detail: "boom" }));
      return Promise.resolve(jsonResponse(200, ME));
    }
    if (url.includes("/orders/claim")) return Promise.resolve(jsonResponse(200, { claimed: 0 }));
    return Promise.resolve(jsonResponse(200, {}));
  });

  const { result } = renderAuth();
  await waitFor(() => {
    expect(result.current.isLoading).toBe(false);
  });

  await act(async () => {
    await result.current.loginWithTelegram({ id: 1 });
  });

  // The session is real, so the app must end up signed in without a reload.
  await waitFor(() => {
    expect(result.current.user).not.toBeNull();
  });
});

it("does not reject the caller when the guest-order claim fails", async () => {
  fetchMock.mockImplementation((url: string) => {
    if (url.includes("/auth/login")) {
      return Promise.resolve(jsonResponse(200, { access_token: "tok" }));
    }
    if (url.includes("/auth/me")) return Promise.resolve(jsonResponse(200, ME));
    if (url.includes("/orders/claim")) return Promise.resolve(jsonResponse(500, {}));
    return Promise.resolve(jsonResponse(200, {}));
  });

  const { result } = renderAuth();
  await waitFor(() => {
    expect(result.current.isLoading).toBe(false);
  });

  await act(async () => {
    await result.current.login("b@e.com", "pw");
  });

  await waitFor(() => {
    expect(result.current.user).not.toBeNull();
  });
});
