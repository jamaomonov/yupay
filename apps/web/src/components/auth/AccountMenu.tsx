"use client";

import { LogOut, Package } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { useLoginModal } from "@/store/useLoginModal";

interface Props {
  locale: string;
}

/**
 * Header account control island.
 *
 * - Loading: renders nothing to avoid a flash of the wrong state.
 * - Unauthenticated: "Войти" link styled as a ghost button matching header siblings.
 * - Authenticated: avatar toggle with a dropdown menu (account, orders, logout).
 *
 * Intentionally uses an initial-letter circle fallback instead of <img> to avoid
 * next.config remotePatterns wiring for Telegram CDN URLs.
 */
export function AccountMenu({ locale }: Props) {
  const t = useTranslations("web.nav");
  const { user, isLoading, logout } = useAuth();
  const openLogin = useLoginModal((s) => s.open);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => {
      document.removeEventListener("mousedown", onDown);
    };
  }, [open]);

  // isLoading stays true on the server + first client render (AuthProvider gates
  // it on `mounted`), so this matches between SSR and hydration.
  if (isLoading) return null;

  if (!user) {
    return (
      <button type="button" onClick={openLogin} className={buttonStyles({ size: "md" })}>
        {t("login")}
      </button>
    );
  }

  const initial = (user.display_name ?? user.email ?? "?")[0]?.toUpperCase() ?? "?";

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={t("menu")}
        className="border-border bg-muted text-tx-mute hover:bg-card-2 hover:text-foreground flex h-11 w-11 items-center justify-center overflow-hidden rounded-full border text-sm font-bold transition"
      >
        {user.photo_url ? (
          // eslint-disable-next-line @next/next/no-img-element -- external Telegram CDN avatar; a plain <img> avoids next/image remotePatterns wiring for a 38px thumbnail
          <img
            src={user.photo_url}
            alt=""
            referrerPolicy="no-referrer"
            className="h-full w-full object-cover"
          />
        ) : (
          initial
        )}
      </button>

      {open && (
        <div
          role="menu"
          className="border-border bg-card/95 absolute right-0 top-11 z-40 min-w-[11rem] overflow-hidden rounded-xl border p-1 shadow-2xl backdrop-blur-xl"
        >
          <Link
            href={`/${locale}/account/orders`}
            role="menuitem"
            onClick={() => {
              setOpen(false);
            }}
            className="text-tx-mute hover:bg-card-2 hover:text-foreground flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition"
          >
            <Package size={16} />
            {t("orders")}
          </Link>
          <div className="border-border my-1 border-t" />
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setOpen(false);
              logout();
            }}
            className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-[#FF6B6B] transition hover:bg-[#FF6B6B]/10"
          >
            <LogOut size={16} />
            {t("logout")}
          </button>
        </div>
      )}
    </div>
  );
}
