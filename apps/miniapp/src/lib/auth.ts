/**
 * Auth: log in via Telegram initData, store tokens, expose the current user.
 *
 * The auth state is split in two layers:
 *
 * - Token storage (``getAccessToken``/``setTokens``) — synchronous, in localStorage.
 *   Used by ``api()`` to attach ``Authorization`` headers.
 * - ``useMe()`` TanStack Query — async; resolves once we have a token and the
 *   ``/auth/me`` round-trip succeeds. Pages gate "needs login" behaviour on this.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  ApiError,
  apiGet,
  apiPost,
  clearTokens,
  getAccessToken,
  setTokens,
} from "./api";
import { isInsideTelegram, readyTelegram, waitForInitData } from "./telegram";

interface TokensOut {
  access_token: string;
  token_type: "Bearer";
  expires_in: number;
  refresh_token?: string | null;
  refresh_expires_in?: number | null;
}

export interface Me {
  id: string;
  email: string | null;
  locale: string;
  /** Storefront/wallet display currency the customer picked (default ``USD``). */
  display_currency: string;
  display_name: string | null;
  photo_url: string | null;
  roles: string[];
  created_at: string;
}

export async function loginWithTelegramInitData(initData: string): Promise<TokensOut> {
  const tokens = await apiPost<TokensOut>(
    "/api/v1/auth/telegram/webapp",
    { init_data: initData },
    { anonymous: true },
  );
  setTokens(tokens.access_token, tokens.refresh_token ?? null);
  return tokens;
}

export type BootstrapStatus = "ok" | "no-telegram" | "no-init-data" | "failed";

export interface BootstrapResult {
  status: BootstrapStatus;
  error?: ApiError | Error;
}

/**
 * Bootstrap auth on app mount.
 *
 * Polls ``Telegram.WebApp.initData`` for up to ``timeoutMs`` ms before giving
 * up. Cold-launches of the Telegram client (especially Android) can render the
 * WebView before the official ``telegram-web-app.js`` has populated initData
 * from the URL hash — without the wait we silently miss it on the first open.
 *
 * Returns a typed result so callers (e.g. ``BootstrapGate``) can show a retry
 * button or fall back to anonymous mode.
 */
export async function bootstrapAuth(
  { timeoutMs }: { timeoutMs?: number } = {},
): Promise<BootstrapResult> {
  readyTelegram();
  // Plain browser dev: keep whatever token is stored; UI surfaces "Open in Telegram".
  if (typeof window === "undefined" || !window.Telegram) {
    return { status: "no-telegram" };
  }
  const initData = await waitForInitData(timeoutMs ?? 2_000);
  if (!initData) {
    // Either not running inside Telegram, or the client never delivered initData.
    return { status: isInsideTelegram() ? "no-init-data" : "no-telegram" };
  }
  try {
    await loginWithTelegramInitData(initData);
    return { status: "ok" };
  } catch (exc) {
    const err = exc instanceof Error ? exc : new Error(String(exc));
    return { status: "failed", error: err };
  }
}

export function useMe() {
  return useQuery<Me | null>({
    queryKey: ["me"],
    queryFn: async () => {
      if (!getAccessToken()) return null;
      try {
        return await apiGet<Me>("/api/v1/auth/me");
      } catch (exc) {
        if (exc instanceof ApiError && (exc.status === 401 || exc.status === 403)) {
          clearTokens();
          return null;
        }
        throw exc;
      }
    },
    staleTime: 60_000,
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation<void, ApiError, void>({
    mutationFn: async () => {
      // Best-effort: backend revokes the refresh token, but we don't block the UI on it.
      clearTokens();
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["me"] });
      void qc.invalidateQueries({ queryKey: ["my-orders"] });
    },
  });
}

/** Whether the current page can perform mutations (create order, buy, …). */
export function useCanTransact(): boolean {
  const me = useMe();
  return Boolean(me.data);
}
