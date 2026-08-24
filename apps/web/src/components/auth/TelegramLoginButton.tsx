"use client";

import { useEffect, useRef } from "react";

import { useTelegramSignIn } from "@/hooks/useTelegramSignIn";

/**
 * Injects Telegram's Login Widget <script>. The widget calls a global callback
 * with the signed user payload, which we POST to /auth/telegram/widget.
 * Requires NEXT_PUBLIC_TELEGRAM_BOT_USERNAME and a BotFather /setdomain binding.
 */
export function TelegramLoginButton() {
  const ref = useRef<HTMLDivElement>(null);
  const signInWithTelegram = useTelegramSignIn();
  const bot = process.env.NEXT_PUBLIC_TELEGRAM_BOT_USERNAME;

  useEffect(() => {
    const el = ref.current;
    if (!el || !bot) return;
    const w = window as unknown as {
      onTelegramAuth?: (u: Record<string, unknown>) => void;
    };
    w.onTelegramAuth = (u) => {
      signInWithTelegram(u);
    };
    const s = document.createElement("script");
    s.src = "https://telegram.org/js/telegram-widget.js?22";
    s.async = true;
    s.setAttribute("data-telegram-login", bot);
    s.setAttribute("data-size", "large");
    s.setAttribute("data-radius", "12");
    s.setAttribute("data-onauth", "onTelegramAuth(user)");
    s.setAttribute("data-request-access", "write");
    el.appendChild(s);
    return () => {
      el.replaceChildren();
    };
  }, [bot, signInWithTelegram]);

  if (!bot) return null;
  return <div ref={ref} />;
}
