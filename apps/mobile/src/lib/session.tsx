/**
 * The signed-in session: a 15-minute access token in memory, the 30-day refresh token in the
 * device keychain (ADR-0101). Sign-in asks for both tokens in the body; every refresh rotates
 * the stored one.
 */
import { ApiError } from "@yupay/api-client";
import type { MeOut } from "@yupay/api-client/types";
import { useQueryClient } from "@tanstack/react-query";
import { randomUUID } from "expo-crypto";
import * as Linking from "expo-linking";
import * as SecureStore from "expo-secure-store";
import * as WebBrowser from "expo-web-browser";
import { createContext, use, useCallback, useEffect, useState, type ReactNode } from "react";
import { Platform } from "react-native";

import { api } from "@/lib/api";
import { encodeState, readResult, type Provider } from "@/lib/social-state";

const V1 = "/api/v1";
const WEB_URL = process.env.EXPO_PUBLIC_WEB_URL ?? "https://yupay.uz";
const REFRESH_KEY = "refresh_token";
const JSON_BODY = { "Content-Type": "application/json" };
/** Recorded on an account the app opens (`users.signup_source`). */
const SURFACE = { "X-Yupay-Surface": "mobile" };
/** Asks the sign-in routes for the refresh token in the JSON (ADR-0101). */
const BODY_TRANSPORT = { "X-Yupay-Token-Transport": "body" };
/** Refresh this long before the access token runs out. */
const EARLY_MS = 60_000;

interface Tokens {
  access_token: string;
  expires_in: number;
  refresh_token?: string;
}

// The keychain on a phone; the web preview has none and keeps nothing across reloads.
async function readRefresh(): Promise<string | null> {
  if (Platform.OS === "web") return null;
  try {
    return await SecureStore.getItemAsync(REFRESH_KEY);
  } catch {
    return null;
  }
}

async function writeRefresh(token: string | null): Promise<void> {
  if (Platform.OS === "web") return;
  try {
    if (token === null) await SecureStore.deleteItemAsync(REFRESH_KEY);
    else await SecureStore.setItemAsync(REFRESH_KEY, token);
  } catch {
    // A token that does not stick costs a sign-in next launch, nothing more.
  }
}

let access: { token: string; until: number } | null = null;
let refreshing: Promise<string | null> | null = null;

async function keep(tokens: Tokens): Promise<string> {
  access = { token: tokens.access_token, until: Date.now() + tokens.expires_in * 1000 };
  // An API without body mode (before the ADR-0101 deploy) answers with no refresh token:
  // the session then lasts as long as the access token.
  if (tokens.refresh_token !== undefined) await writeRefresh(tokens.refresh_token);
  return tokens.access_token;
}

/** One refresh at a time: two screens asking at once share it. */
function refreshAccess(): Promise<string | null> {
  refreshing ??= (async () => {
    const stored = await readRefresh();
    if (stored === null) return null;
    try {
      const tokens = await api.request<Tokens>(`${V1}/auth/refresh`, {
        method: "POST",
        headers: JSON_BODY,
        body: JSON.stringify({ refresh_token: stored }),
      });
      return await keep(tokens);
    } catch (err) {
      // Only a refusal ends the session. A dropped connection is thrown, not read as
      // "signed out": the stored token is still good for the next try.
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        await writeRefresh(null);
        access = null;
        return null;
      }
      throw err;
    }
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

async function accessToken(): Promise<string | null> {
  if (access !== null && access.until - EARLY_MS > Date.now()) return access.token;
  return refreshAccess();
}

/** An API call as the signed-in user; a 401 refreshes once and tries again. */
export async function authRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await accessToken();
  if (token === null) throw new ApiError(401, "Unauthorized", "no session");
  const headers = (bearer: string) => ({
    ...(init.headers ?? {}),
    Authorization: `Bearer ${bearer}`,
  });
  try {
    return await api.request<T>(path, { ...init, headers: headers(token) });
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 401) throw err;
    access = null;
    const fresh = await refreshAccess();
    if (fresh === null) throw err;
    return api.request<T>(path, { ...init, headers: headers(fresh) });
  }
}

/** Thrown when the provider's page answered with an error or for another attempt. */
export class SocialSignInError extends Error {}

/**
 * The stored session's account, `null` when there is none (or the server refused it). A
 * network failure is thrown: the session may be fine, the phone is just offline.
 */
async function restoreSession(): Promise<MeOut | null> {
  try {
    return await authRequest<MeOut>(`${V1}/auth/me`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) return null;
    throw err;
  }
}

/** Opens an account by email; the confirmation link finishes it (no session yet). */
export async function register(email: string, password: string, locale: string): Promise<void> {
  await api.request(`${V1}/auth/register`, {
    method: "POST",
    headers: { ...JSON_BODY, ...SURFACE },
    body: JSON.stringify({ email: email.trim().toLowerCase(), password, locale }),
  });
}

interface SessionValue {
  /** `undefined` while the stored session is being restored. */
  user: MeOut | null | undefined;
  /** The restore failed for want of a connection; `retry` tries again. */
  offline: boolean;
  retry: () => void;
  /** Re-reads the account after something changed it. */
  reload: () => Promise<void>;
  signIn: (email: string, password: string) => Promise<void>;
  /**
   * Google or Telegram through the storefront's `/app-auth` page in the system browser.
   * Resolves `false` when the buyer closed it, `true` once signed in.
   */
  signInWith: (provider: Provider, locale: string) => Promise<boolean>;
  signOut: () => Promise<void>;
}

const SessionContext = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MeOut | null | undefined>(undefined);
  const queryClient = useQueryClient();

  const loadMe = useCallback(async () => {
    try {
      setUser(await restoreSession());
    } catch {
      // Offline: keep what is on screen; the next read tries again.
    }
  }, []);

  const [offline, setOffline] = useState(false);
  const [attempt, setAttempt] = useState(0);

  // Restore the stored session at launch, and again on «retry».
  useEffect(() => {
    restoreSession().then(
      (me) => {
        setOffline(false);
        setUser(me);
      },
      () => setOffline(true),
    );
  }, [attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  /** Posts a credential to a sign-in route and adopts the session it returns. */
  const finish = useCallback(
    async (path: string, body: unknown) => {
      const tokens = await api.request<Tokens>(`${V1}${path}`, {
        method: "POST",
        headers: { ...JSON_BODY, ...SURFACE, ...BODY_TRANSPORT },
        body: JSON.stringify(body),
      });
      await keep(tokens);
      await loadMe();
      await queryClient.invalidateQueries({ queryKey: ["account"] });
    },
    [loadMe, queryClient],
  );

  const signIn = useCallback(
    (email: string, password: string) =>
      finish("/auth/login", { email: email.trim().toLowerCase(), password }),
    [finish],
  );

  const signInWith = useCallback(
    async (provider: Provider, locale: string) => {
      const returnTo = Linking.createURL("auth");
      const state = encodeState(returnTo, randomUUID(), locale);
      const start = `${WEB_URL}/app-auth?provider=${provider}&state=${state}`;
      const outcome = await WebBrowser.openAuthSessionAsync(start, returnTo);
      if (outcome.type !== "success") return false;
      const params = Object.fromEntries(
        Object.entries(Linking.parse(outcome.url).queryParams ?? {}).map(([key, value]) => [
          key,
          Array.isArray(value) ? value[0] : value,
        ]),
      );
      const result = readResult(params, state);
      if ("error" in result) throw new SocialSignInError(provider);
      if (result.provider === "google") {
        await finish("/auth/google", { access_token: result.accessToken });
      } else {
        await finish("/auth/telegram/widget", result.payload);
      }
      return true;
    },
    [finish],
  );

  const signOut = useCallback(async () => {
    const stored = await readRefresh();
    const bearer = access?.token;
    access = null;
    await writeRefresh(null);
    setUser(null);
    queryClient.removeQueries({ queryKey: ["account"] });
    try {
      await api.request(`${V1}/auth/logout`, {
        method: "POST",
        headers: { ...JSON_BODY, ...(bearer ? { Authorization: `Bearer ${bearer}` } : {}) },
        body: JSON.stringify(stored !== null ? { refresh_token: stored } : {}),
      });
    } catch {
      // Signed out on the phone either way; the server session dies with its TTL.
    }
  }, [queryClient]);

  return (
    <SessionContext value={{ user, offline, retry, reload: loadMe, signIn, signInWith, signOut }}>
      {children}
    </SessionContext>
  );
}

export function useSession(): SessionValue {
  const value = use(SessionContext);
  if (value === null) throw new Error("useSession outside SessionProvider");
  return value;
}
