import { Plus, Wallet as WalletIcon } from "lucide-react";
import { Link } from "wouter";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useMe } from "@/lib/auth";
import { useDisplayCurrency } from "@/lib/currency";
import { useT } from "@/lib/i18n";
import {
  formatBalance,
  groupBalancesByCurrency,
  pickPrimaryBalance,
  useWallet,
} from "@/lib/wallet";

export function Header() {
  const me = useMe();
  const { t, tn } = useT();
  const wallet = useWallet();
  const homeCurrency = useDisplayCurrency();
  // The pill used to live-convert every balance into the user's
  // displayCurrency and show one figure. Multi-currency wallets break
  // that — a fixed FX rate would lie. Show the user's home currency
  // first (when it has a non-zero balance), badge other non-zero
  // currencies as ``+N``.
  const grouped = groupBalancesByCurrency(wallet.data ?? []);
  const balance = pickPrimaryBalance(grouped, homeCurrency);
  const others = grouped.filter((g) => g.amount !== 0 && g.currency !== balance?.currency);
  const extraCount = others.length;
  const user = me.data;

  return (
    // The header is anchored to the very top of the viewport and
    // pads its content down by 83 px so the brand row sits below
    // Telegram's floating close/back chip on iOS / Android. The full
    // 0..147 px strip carries the same blurred background, so nothing
    // shows through above the brand row. (We can't depend on
    // Telegram's CSS variables — they hydrate async; a fixed offset
    // is the simplest thing that works everywhere.)
    <header className="bg-background/80 border-border fixed left-0 right-0 top-0 z-50 mx-auto flex h-[147px] max-w-[430px] items-center justify-between border-b px-4 pt-[83px] backdrop-blur-xl">
      {/* Brand — full wordmark SVG. Lives in apps/miniapp/public/, the
          path is unhashed because Vite passes /logo-wordmark.svg through
          as-is for public assets. ``alt`` is the brand name so screen
          readers / Telegram link previews still read "YuPay" even if the
          asset 404s. */}
      <Link href="/" className="flex items-center" aria-label={t("header.logoAlt")}>
        <img
          src="/logo-wordmark.svg"
          alt={t("header.logoAlt")}
          className="h-8 w-auto"
          draggable={false}
        />
      </Link>

      {/* Balance pill + top-up + avatar.
          The balance pill and the + button used to be a single Link to
          /wallet — operators kept clicking + expecting the top-up screen
          and landing on the balance overview instead. They're now two
          adjacent links so the + is a one-tap shortcut to /wallet/topup. */}
      <div className="flex items-center gap-2">
        <div
          className="border-border bg-card flex h-9 items-stretch overflow-hidden rounded-full border"
          data-testid="header-wallet"
        >
          <Link
            href="/wallet"
            className="flex items-center gap-1.5 pl-3 pr-2"
            aria-label={t("header.openWallet")}
          >
            <WalletIcon size={12} className="text-white/40" />
            <span className="text-sm font-bold tabular-nums leading-none text-white">
              {user && balance ? formatBalance(balance.amount, balance.currency) : "—"}
            </span>
            {extraCount > 0 && (
              <span
                className="rounded-full px-1.5 py-0.5 text-[10px] font-bold leading-none"
                style={{
                  background: "hsl(var(--surface-2))",
                  color: "rgba(255,255,255,0.55)",
                }}
                aria-label={tn("header.moreCurrencies", extraCount)}
                title={others.map((g) => formatBalance(g.amount, g.currency)).join(" · ")}
              >
                +{extraCount.toString()}
              </span>
            )}
          </Link>
          <Link
            href="/wallet/topup"
            className="flex w-9 items-center justify-center transition-colors"
            style={{ background: "hsl(var(--primary))", color: "#000" }}
            aria-label={t("header.topUp")}
            data-testid="header-topup"
          >
            <Plus size={16} strokeWidth={3} />
          </Link>
        </div>

        <Link href="/settings" aria-label={t("header.profile")}>
          <Avatar className="border-border h-9 w-9 border">
            {user?.photo_url ? (
              <AvatarImage src={user.photo_url} alt={user.display_name ?? "user"} />
            ) : (
              <AvatarImage
                src={`https://api.dicebear.com/9.x/pixel-art/svg?seed=${
                  user?.id ?? "anon"
                }&backgroundColor=1e2a3a`}
              />
            )}
            <AvatarFallback className="bg-primary/20 text-primary text-xs font-bold">
              {(user?.display_name?.[0] ?? "?").toUpperCase()}
            </AvatarFallback>
          </Avatar>
        </Link>
      </div>
    </header>
  );
}
