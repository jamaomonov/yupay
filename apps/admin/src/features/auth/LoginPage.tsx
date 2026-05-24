/** Login screen.
 *
 * Two paths:
 *  - Telegram Login Widget (production path).
 *  - DEV-only login/password form, shown when the backend reports the dev endpoint
 *    is active (`GET /api/v1/auth/admin-dev/enabled`).
 */

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useNavigate, useLocation } from "react-router-dom";
import { z } from "zod";

import { useAuthStore } from "./authStore";

import { apiGet, apiPost, ApiError } from "@/lib/api";

interface TelegramAuthPayload {
  id: number;
  first_name: string;
  last_name?: string;
  username?: string;
  photo_url?: string;
  auth_date: number;
  hash: string;
}

interface TokensOut {
  access_token: string;
  refresh_token: string | null;
}

const BOT_USERNAME = import.meta.env.VITE_TELEGRAM_BOT_USERNAME;

declare global {
  interface Window {
    onTelegramAuth?: (payload: TelegramAuthPayload) => void;
  }
}

const devSchema = z.object({
  login: z.string().min(1),
  password: z.string().min(1),
});
type DevForm = z.infer<typeof devSchema>;

export function LoginPage() {
  const setSession = useAuthStore((s) => s.setSession);
  const navigate = useNavigate();
  const location = useLocation();
  const widgetSlot = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const devEnabled = useQuery<{ enabled: boolean }>({
    queryKey: ["admin-dev-enabled"],
    queryFn: () => apiGet<{ enabled: boolean }>("/api/v1/auth/admin-dev/enabled"),
    retry: false,
    staleTime: 60_000,
  });

  const goNext = useCallback(
    (tokens: TokensOut) => {
      setSession(tokens.access_token, tokens.refresh_token);
      const target = (location.state as { from?: string } | null)?.from ?? "/";
      navigate(target, { replace: true });
    },
    [navigate, location.state, setSession],
  );

  const onTelegramAuth = useCallback(
    async (payload: TelegramAuthPayload) => {
      setBusy(true);
      setError(null);
      try {
        const tokens = await apiPost<TokensOut>("/api/v1/auth/telegram/widget", payload);
        goNext(tokens);
      } catch (e) {
        setError(
          e instanceof ApiError && e.status === 401
            ? "Telegram сигнатура не прошла."
            : "Не удалось войти.",
        );
      } finally {
        setBusy(false);
      }
    },
    [goNext],
  );

  useEffect(() => {
    window.onTelegramAuth = (p) => void onTelegramAuth(p);
    if (!BOT_USERNAME || !widgetSlot.current) return undefined;
    const script = document.createElement("script");
    script.src = "https://telegram.org/js/telegram-widget.js?22";
    script.async = true;
    script.setAttribute("data-telegram-login", BOT_USERNAME);
    script.setAttribute("data-size", "large");
    script.setAttribute("data-radius", "8");
    script.setAttribute("data-onauth", "onTelegramAuth(user)");
    script.setAttribute("data-request-access", "write");
    widgetSlot.current.append(script);
    const slot = widgetSlot.current;
    return () => {
      slot.replaceChildren();
      delete window.onTelegramAuth;
    };
  }, [onTelegramAuth]);

  const form = useForm<DevForm>({
    resolver: zodResolver(devSchema),
    defaultValues: { login: "", password: "" },
  });

  const onDevSubmit = form.handleSubmit(async (values) => {
    setBusy(true);
    setError(null);
    try {
      const tokens = await apiPost<TokensOut>("/api/v1/auth/admin-dev", values);
      goNext(tokens);
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 401
          ? "Неверный логин или пароль."
          : "Не удалось войти.",
      );
    } finally {
      setBusy(false);
    }
  });

  const showDev = devEnabled.data?.enabled === true;
  const showTelegram = !!BOT_USERNAME;

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border bg-[var(--bg-surface)] p-8 shadow-md">
        <h1 className="text-2xl font-semibold">YuPay Admin</h1>
        <p className="mt-2 text-sm text-[var(--text-secondary)]">Доступ только для админов.</p>

        {showDev && (
          <form onSubmit={onDevSubmit} className="mt-6 space-y-3">
            <label className="block">
              <span className="text-xs font-medium uppercase text-[var(--text-secondary)]">
                Логин
              </span>
              <Input
                {...form.register("login")}
                autoComplete="username"
                placeholder="admin"
                className="mt-1"
              />
            </label>
            <label className="block">
              <span className="text-xs font-medium uppercase text-[var(--text-secondary)]">
                Пароль
              </span>
              <Input
                {...form.register("password")}
                type="password"
                autoComplete="current-password"
                className="mt-1"
              />
            </label>
            <Button type="submit" disabled={busy} className="w-full">
              {busy ? "Вход…" : "Войти"}
            </Button>
            <p className="text-xs text-[var(--text-secondary)]">
              Это dev-вход. Отключи в prod через <code>ADMIN_DEV_LOGIN_ENABLED=false</code>.
            </p>
          </form>
        )}

        {showTelegram && (
          <>
            {showDev && (
              <div className="my-6 flex items-center gap-3 text-xs uppercase text-[var(--text-secondary)]">
                <span className="h-px flex-1 bg-[var(--color-border)]" />
                или
                <span className="h-px flex-1 bg-[var(--color-border)]" />
              </div>
            )}
            <div ref={widgetSlot} className="flex justify-center" />
          </>
        )}

        {!showDev && !showTelegram && (
          <div className="mt-6 rounded-md bg-[var(--bg-muted)] p-4 text-sm">
            <p className="font-medium">Способы входа не настроены.</p>
            <p className="mt-1 text-[var(--text-secondary)]">
              Установи <code>VITE_TELEGRAM_BOT_USERNAME</code> или включи{" "}
              <code>ADMIN_DEV_LOGIN_ENABLED=true</code>.
            </p>
          </div>
        )}

        {error && (
          <p className="bg-[var(--color-danger)]/10 mt-4 rounded-md p-3 text-sm text-[var(--danger)]">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}
