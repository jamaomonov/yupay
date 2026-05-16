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
import { getWebApp, isInsideTelegram, readyTelegram } from "./telegram";

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

/**
 * Bootstrap auth on app mount.
 *
 * - Inside Telegram (``initData`` non-empty): always re-log; tokens may have rotated.
 * - Outside Telegram (plain browser dev): keep whatever token is stored; pages will
 *   detect missing ``me`` and surface an "Open in Telegram" banner.
 */
export async function bootstrapAuth(): Promise<void> {
  readyTelegram();
  if (!isInsideTelegram()) return;
  const initData = getWebApp()?.initData;
  if (!initData) return;
  try {
    await loginWithTelegramInitData(initData);
  } catch (exc) {
    // Telegram auth failed (bad HMAC, server down) — just log and continue. The user
    // will see anonymous-only state and can retry by reopening the miniapp.
    console.warn("Telegram auth bootstrap failed", exc);
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
