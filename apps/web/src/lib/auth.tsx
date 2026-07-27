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

import { apiFetch, clearTokens, getAccessToken, setTokens, type Tokens } from "./client";

export interface Me {
  id: string;
  email: string | null;
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
  register: (email: string, password: string, locale: string) => Promise<void>;
  loginWithTelegram: (payload: Record<string, unknown>) => Promise<void>;
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
    setMounted(true);
  }, []);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<Me>("/auth/me"),
    enabled: typeof window !== "undefined" && Boolean(getAccessToken()),
    retry: false,
    staleTime: 60_000,
  });

  const afterTokens = useCallback(
    async (tokens: Tokens) => {
      // Only the access token is in the body now; the refresh token arrived as an
      // HttpOnly cookie (set by the browser from the login/register response).
      setTokens(tokens.access_token);
      // Fetch /auth/me imperatively and seed the cache. `invalidateQueries`
      // would no-op here because the `me` query is still `enabled: false` (its
      // gate was evaluated before the token landed in localStorage); fetchQuery
      // ignores that gate, so `user` is populated before the caller navigates
      // to an auth-gated route.
      await qc.fetchQuery({ queryKey: ["me"], queryFn: () => apiFetch<Me>("/auth/me") });
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

  const register = useCallback(
    async (email: string, password: string, locale: string) => {
      const tokens = await apiFetch<Tokens>("/auth/register", {
        method: "POST",
        anonymous: true,
        body: { email, password, locale },
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

  const logout = useCallback(() => {
    // Best-effort: ask the server to revoke the session and clear the HttpOnly
    // refresh cookie (JS can't delete it itself). Don't block the UI on it.
    void apiFetch("/auth/logout", { method: "POST" }).catch(() => {});
    clearTokens();
    qc.setQueryData(["me"], null);
    void qc.invalidateQueries({ queryKey: ["me"] });
  }, [qc]);

  const value = useMemo<AuthValue>(
    () => ({
      user: meQuery.data ?? null,
      isLoading: !mounted || meQuery.isLoading,
      login,
      register,
      loginWithTelegram,
      logout,
    }),
    [mounted, meQuery.data, meQuery.isLoading, login, register, loginWithTelegram, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
