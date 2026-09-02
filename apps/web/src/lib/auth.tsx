"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import {
  apiFetch,
  clearTokens,
  getAccessToken,
  hasSessionHint,
  refreshAccess,
  setTokens,
  type Tokens,
} from "./client";
import { listGuestOrders, removeGuestOrders } from "./guest-orders";

export interface Me {
  id: string;
  email: string | null;
  /** Where this customer's orders are mailed, when they have set one.
   *  Distinct from `email`, which is the login identity. */
  delivery_email?: string | null;
  locale: string;
  display_currency: string;
  display_name: string | null;
  photo_url: string | null;
  roles: string[];
  created_at: string;
}

interface AuthValue {
  user: Me | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  /**
   * Creates the account but opens no session — the API now requires email
   * verification before password login works (`RegisterOut.status ===
   * "verification_required"`). Callers show verify-your-email copy on success;
   * they already have the submitted `email` to render it with.
   */
  register: (email: string, password: string, locale: string) => Promise<void>;
  loginWithTelegram: (payload: Record<string, unknown>) => Promise<void>;
  /** Redeems a Google GIS credential (`POST /auth/google`) and opens a session. */
  loginWithGoogle: (credential: string) => Promise<void>;
  /** Redeems a `POST /auth/verify-email` token and opens a session (afterTokens). */
  verifyEmail: (token: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  // Auth state derives from localStorage, invisible to the server. Stay
  // "loading" until mounted so every auth-gated consumer (header, /account)
  // renders the same thing on the server and the first client render — without
  // this they diverge and React throws a hydration mismatch.
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    let cancelled = false;
    // The access token lives in memory only, so it's gone after a reload. If a
    // prior session hint exists, re-hydrate it from the HttpOnly refresh cookie
    // before we let the `me` query run; no hint (anonymous) → skip the refresh
    // call entirely. `mounted` flips only once this settles so the query's
    // `enabled` gate sees the re-hydrated token.
    (async () => {
      if (!getAccessToken() && hasSessionHint()) {
        await refreshAccess();
      }
      if (!cancelled) setMounted(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<Me>("/auth/me"),
    enabled: mounted && typeof window !== "undefined" && Boolean(getAccessToken()),
    retry: false,
    staleTime: 60_000,
  });

  const afterTokens = useCallback(
    async (tokens: Tokens) => {
      // Only the access token is in the body now; the refresh token arrived as an
      // HttpOnly cookie (set by the browser from the login/register response).
      setTokens(tokens.access_token);
      // Seed the cache before the caller navigates to an auth-gated route.
      // `setTokens` above has already told the provider it is signed in, so by
      // the time this lands the `me` observer is enabled and publishes it.
      //
      // Failure must not abort: the session is already real by this point —
      // the token is held and the refresh cookie is set — so throwing here left
      // a signed-in browser showing a signed-out app, and `TelegramLoginButton`
      // calls this as `void loginWithTelegram(u)`, so nothing surfaced. A
      // reload then "fixed" it by taking the cookie path instead. The enabled
      // `me` query owns the retry; this is only a head start.
      await qc
        .fetchQuery({ queryKey: ["me"], queryFn: () => apiFetch<Me>("/auth/me") })
        .catch(() => {
          // Drop the failed entry rather than leave it: the query is
          // `retry: false`, so an observer enabling onto an errored `me` would
          // inherit the error and never ask again. Removed, it starts clean and
          // fetches — which is the recovery this whole branch exists for.
          qc.removeQueries({ queryKey: ["me"] });
        });

      // Migrate this browser's guest orders (if any) onto the now-authenticated
      // account, then drop the local copies — they're either claimed onto this
      // account or belonged to a different email and were never claimable here
      // either way. Non-fatal: a claim failure shouldn't block sign-in.
      try {
        await apiFetch<{ claimed: number }>("/orders/claim", { method: "POST" });
      } catch {
        /* best-effort — claim errors don't block sign-in */
      }
      removeGuestOrders(listGuestOrders().map((o) => o.orderId));
      void qc.invalidateQueries({ queryKey: ["orders"] });
      // Remove, not invalidate: an invalidated entry is still served while the
      // refetch is in flight, and the account control renders `wallet.data`
      // ungated — so the previous person's balance would show first. Signing in
      // without a reload keeps the same QueryClient, which is what makes this
      // reachable at all.
      qc.removeQueries({ queryKey: ["wallet"] });
    },
    [qc],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await apiFetch<Tokens>("/auth/login", {
        method: "POST",
        anonymous: true,
        body: { email, password },
      });
      await afterTokens(tokens);
    },
    [afterTokens],
  );

  const register = useCallback(async (email: string, password: string, locale: string) => {
    // No session comes back — the account exists but needs email verification
    // (POST /auth/verify-email) before it can log in. The response body is just
    // `{status: "verification_required", email}`; callers already hold `email`.
    await apiFetch<{ status: "verification_required"; email: string }>("/auth/register", {
      method: "POST",
      anonymous: true,
      body: { email, password, locale },
    });
  }, []);

  const verifyEmail = useCallback(
    async (token: string) => {
      const tokens = await apiFetch<Tokens>("/auth/verify-email", {
        method: "POST",
        anonymous: true,
        body: { token },
      });
      await afterTokens(tokens);
    },
    [afterTokens],
  );

  const loginWithTelegram = useCallback(
    async (payload: Record<string, unknown>) => {
      const tokens = await apiFetch<Tokens>("/auth/telegram/widget", {
        method: "POST",
        anonymous: true,
        body: payload,
      });
      await afterTokens(tokens);
    },
    [afterTokens],
  );

  const loginWithGoogle = useCallback(
    async (credential: string) => {
      const tokens = await apiFetch<Tokens>("/auth/google", {
        method: "POST",
        anonymous: true,
        body: { credential },
      });
      await afterTokens(tokens);
    },
    [afterTokens],
  );

  const logout = useCallback(() => {
    // Best-effort: ask the server to revoke the session and clear the HttpOnly
    // refresh cookie (JS can't delete it itself). Don't block the UI on it.
    void apiFetch("/auth/logout", { method: "POST" }).catch(() => {
      /* best-effort logout — ignore network/revocation errors */
    });
    clearTokens();
    // `me` is written, not dropped — and written *before* anything is removed.
    //
    // The obvious version of this (`qc.clear()`, then re-seed `me` to null)
    // signed nobody out: pressing "sign out" changed nothing on screen until
    // the page was reloaded. `clear()` destroys every query object in the
    // cache, and this provider's live observer stays attached to the destroyed
    // one; the `setQueryData` that follows *builds a new query object* — a
    // different instance, with zero observers — so the signed-out state landed
    // somewhere nothing was listening. Verified rather than assumed: after
    // that pair the new query has no observers and the old observer still
    // reports the previous account's data.
    //
    // Writing to the still-live query notifies the observer that is actually
    // subscribed, which is what re-renders the header and every auth gate.
    qc.setQueryData(["me"], null);
    // Everything else did belong to the account that just left. On a shared
    // device the next person signs in without a reload, so the same
    // QueryClient survives — and TanStack serves cached data while it
    // refetches, which for the wallet means one customer briefly seeing
    // another's balance and ledger history. `me` is excluded because it now
    // holds the signed-out state published above, not stale account data.
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    // `qc.clear()` used to take the mutation cache with it; keep that.
    qc.getMutationCache().clear();
  }, [qc]);

  const value = useMemo<AuthValue>(
    () => ({
      user: meQuery.data ?? null,
      isLoading: !mounted || meQuery.isLoading,
      login,
      register,
      loginWithTelegram,
      loginWithGoogle,
      verifyEmail,
      logout,
    }),
    [
      mounted,
      meQuery.data,
      meQuery.isLoading,
      login,
      register,
      loginWithTelegram,
      loginWithGoogle,
      verifyEmail,
      logout,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
