"use client";

import { useQuery } from "@tanstack/react-query";
import { LogOut, Package, Plus } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import { WalletMark } from "@/components/icons/WalletMark";
import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { listGuestOrders } from "@/lib/guest-orders";
import { pathFor } from "@/lib/seo";
import { formatUzs } from "@/lib/seo";
import { getWallet, WALLET_CURRENCY } from "@/lib/wallet";
import { spendableBalance } from "@/lib/wallet-balance";
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
  // Read here rather than in a sibling chip: one control is easier to place
  // than two, and this one already exists on both the desktop and the mobile
  // header — which is how the balance reaches a phone at all.
  const wallet = useQuery({
    queryKey: ["wallet"],
    queryFn: getWallet,
    enabled: Boolean(user),
    staleTime: 30_000,
  });
  const wrapRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    // Escape too: the mobile sheet twenty lines away has always closed on it,
    // and a dropdown that only answers the mouse strands a keyboard user.
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  // isLoading stays true on the server + first client render (AuthProvider gates
  // it on `mounted`), so this matches between SSR and hydration.
  // Reserve the geometry instead of rendering nothing: returning null left the
  // header's right side empty until auth resolved, then inserted a 44px button
  // and shoved the burger sideways — on every page load.
  // Matches the signed-in pill's resting width so the row does not jump when
  // auth resolves. (Guests get a narrower control; that swap is one shift,
  // not the three this used to produce.)
  if (isLoading) return <div className="h-11 w-[148px]" aria-hidden />;

  if (!user) {
    // Guests have no account, but their orders are remembered in this browser's
    // localStorage (see saveGuestOrder) and /account/orders renders them. Surface
    // a "My orders" link when any exist, so a guest who left the order page can
    // get back to it without the delivered-email link or a typed URL.
    const hasGuestOrders = listGuestOrders().length > 0;
    return (
      <div className="flex items-center gap-2">
        {hasGuestOrders && (
          <Link
            href={pathFor(locale, "/account/orders")}
            className={buttonStyles({ variant: "ghost", size: "md" })}
          >
            <Package size={16} />
            {t("orders")}
          </Link>
        )}
        {/* Ghost, as this file's own docstring has always said. In primary it
            was the single filled lime control on all 30 pages — the loudest
            thing on the site pointed at authentication, on a storefront whose
            checkout is deliberately guest-friendly, and on a brand page it
            competed with the lime "Оплатить" at the bottom. */}
        <button
          type="button"
          onClick={openLogin}
          className={buttonStyles({ variant: "ghost", size: "md" })}
        >
          {t("login")}
        </button>
      </div>
    );
  }

  const initial = (user.display_name ?? user.email ?? "?")[0]?.toUpperCase() ?? "?";
  const balance = spendableBalance(wallet.data?.balances ?? null, WALLET_CURRENCY);
  const balanceLabel = balance === null ? "" : formatUzs(locale, Math.round(balance));

  return (
    <div ref={wrapRef} className="relative">
      {/* Balance and avatar in one control. Two pills side by side competed
          for the same corner; merged, the amount rides next to the avatar on
          every breakpoint. One destination — the menu — so a tap is never
          ambiguous. */}
      <button
        type="button"
        onClick={() => {
          setOpen((v) => !v);
        }}
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={balance === null ? t("menu") : `${t("wallet")}: ${balanceLabel}, ${t("menu")}`}
        className="border-border bg-muted hover:bg-card-2 flex h-11 max-w-full items-center gap-1.5 overflow-hidden rounded-full border pl-2.5 pr-1 transition sm:gap-2 sm:pl-3"
      >
        {/* Same lockup as desktop: mark + amount + avatar. The amount may
            shrink so a long figure does not shove the burger off a 320px bar. */}
        <span className="flex min-w-0 shrink items-center gap-1.5 sm:gap-2">
          <WalletMark size={15} className="text-tx-mute shrink-0" />
          {balance === null ? (
            // A fixed slot, not nothing: the pill was born at 54px and grew to
            // 126+ when the balance landed, moving the lime CTA 62px sideways
            // after first paint — under a finger already on its way down.
            <span className="bg-card-2 h-4 w-[72px] animate-pulse rounded" aria-hidden />
          ) : (
            <span className="text-foreground truncate text-xs font-bold tabular-nums sm:text-sm">
              {balanceLabel}
            </span>
          )}
        </span>
        <span className="bg-card-2 text-tx-mute flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-full text-sm font-bold">
          {user.photo_url ? (
            // eslint-disable-next-line @next/next/no-img-element -- external Telegram CDN avatar; a plain <img> avoids next/image remotePatterns wiring for a 36px thumbnail
            <img
              src={user.photo_url}
              alt=""
              referrerPolicy="no-referrer"
              className="h-full w-full object-cover"
            />
          ) : (
            initial
          )}
        </span>
      </button>

      {open && (
        <div className="border-border bg-card/95 absolute right-0 top-11 z-40 min-w-[11rem] overflow-hidden rounded-xl border p-1 shadow-2xl backdrop-blur-xl">
          <Link
            href={pathFor(locale, "/account/wallet")}
            onClick={() => {
              setOpen(false);
            }}
            className="text-tx-mute hover:bg-card-2 hover:text-foreground flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition"
          >
            <WalletMark size={16} />
            <span className="flex-1">{t("wallet")}</span>
            {balance !== null && (
              <span className="text-foreground text-sm font-bold tabular-nums">{balanceLabel}</span>
            )}
          </Link>
          {/* The one place "Пополнить" means the wallet. The header's own
              lime CTA sells games, which is why it no longer says this. */}
          <Link
            href={pathFor(locale, "/account/wallet/top-up")}
            onClick={() => {
              setOpen(false);
            }}
            className="text-tx-mute hover:bg-card-2 hover:text-foreground flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition"
          >
            <Plus size={16} />
            {t("walletTopUp")}
          </Link>
          <Link
            href={pathFor(locale, "/account/orders")}
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
