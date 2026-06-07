"use client";

import { Mail, X } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useRef, useState } from "react";

import { AuthForm } from "./AuthForm";
import { ProviderButton } from "./ProviderButton";
import { GoogleIcon, SteamIcon, TelegramIcon } from "./ProviderIcons";

import { useAuth } from "@/lib/auth";
import { useLoginModal } from "@/store/useLoginModal";

interface TelegramAuth {
  Login?: {
    auth: (
      opts: { bot_id: number; request_access?: string },
      cb: (user: Record<string, unknown> | false) => void,
    ) => void;
  };
}

const BOT_ID = process.env.NEXT_PUBLIC_TELEGRAM_BOT_ID;

export function LoginModal({ locale }: { locale: string }) {
  const t = useTranslations("web.auth");
  const { isOpen, close } = useLoginModal();
  const { login, register, loginWithTelegram } = useAuth();
  const [screen, setScreen] = useState<"providers" | "email">("providers");
  const [mode, setMode] = useState<"login" | "register">("login");
  const cardRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (isOpen) {
      setScreen("providers");
      setMode("login");
    }
  }, [isOpen]);

  // Focus management: move focus into the dialog on open, restore it to the
  // element that opened the modal on close (WCAG 2.4.3 focus order).
  useEffect(() => {
    if (isOpen) {
      openerRef.current = document.activeElement as HTMLElement | null;
      cardRef.current?.focus();
    } else {
      openerRef.current?.focus();
      openerRef.current = null;
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [isOpen, close]);

  // Load Telegram's widget script once so window.Telegram.Login.auth (the popup
  // used by the custom Telegram tile) is available. The official widget button
  // in the no-BOT_ID fallback loads it too; this covers the BOT_ID branch.
  useEffect(() => {
    if (!isOpen || !BOT_ID) return;
    const SRC = "https://telegram.org/js/telegram-widget.js?22";
    if (document.querySelector(`script[src="${SRC}"]`)) return;
    const s = document.createElement("script");
    s.src = SRC;
    s.async = true;
    document.body.appendChild(s);
  }, [isOpen]);

  const onTelegram = useCallback(() => {
    const tg = (window as unknown as { Telegram?: TelegramAuth }).Telegram;
    if (BOT_ID && tg?.Login?.auth) {
      tg.Login.auth({ bot_id: Number(BOT_ID), request_access: "write" }, (user) => {
        if (user) void loginWithTelegram(user);
      });
    }
  }, [loginWithTelegram]);

  if (!isOpen) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("modalTitle")}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
    >
      <button
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        onClick={close}
        className="bg-bg/80 absolute inset-0 backdrop-blur-sm"
      />
      <div
        ref={cardRef}
        tabIndex={-1}
        className="border-border bg-card relative z-10 w-full max-w-[420px] rounded-2xl border p-7 shadow-2xl outline-none"
      >
        <button
          type="button"
          onClick={close}
          aria-label="Close"
          className="text-tx-mute hover:bg-muted hover:text-foreground absolute right-4 top-4 flex h-8 w-8 items-center justify-center rounded-full transition"
        >
          <X size={18} />
        </button>

        <h2 className="font-display max-w-[16rem] text-2xl font-bold leading-tight tracking-[-0.02em]">
          {t("modalTitle")}
        </h2>

        {screen === "providers" ? (
          <>
            <div className="mt-6 grid grid-cols-2 gap-3">
              <ProviderButton
                label={t("providerEmail")}
                icon={<Mail size={18} />}
                surface="bg-muted text-foreground border border-border"
                onClick={() => {
                  setScreen("email");
                }}
              />
              <ProviderButton
                label={t("providerGoogle")}
                icon={<GoogleIcon />}
                surface="bg-white text-[#1f1f1f]"
                soon
              />
              <ProviderButton
                label={t("providerSteam")}
                icon={<SteamIcon />}
                surface="bg-[#1b2838] text-white"
                soon
              />
              <ProviderButton
                label={t("providerTelegram")}
                icon={<TelegramIcon />}
                surface="bg-[#2AABEE] text-white"
                onClick={onTelegram}
              />
            </div>

            <p className="text-tx-dim mt-6 text-center text-xs leading-relaxed">
              {t("agreePrefix")}{" "}
              <Link href={`/${locale}/legal/privacy`} className="hover:text-tx underline">
                {t("privacy")}
              </Link>{" "}
              {t("and")}{" "}
              <Link href={`/${locale}/legal/terms`} className="hover:text-tx underline">
                {t("terms")}
              </Link>
            </p>
          </>
        ) : (
          <div className="mt-6">
            <button
              type="button"
              onClick={() => {
                setScreen("providers");
              }}
              className="text-tx-mute hover:text-tx mb-4 text-[13px]"
            >
              ← {t("back")}
            </button>
            <AuthForm
              mode={mode}
              locale={locale}
              showTelegram={false}
              onToggleMode={() => {
                setMode((m) => (m === "login" ? "register" : "login"));
              }}
              onSubmit={async (v) => {
                if (mode === "register") {
                  await register(v.email, v.password, locale);
                } else {
                  await login(v.email, v.password);
                }
                // Stay on the current page — the header reflects the signed-in
                // state; no dedicated account page to navigate to.
                close();
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
