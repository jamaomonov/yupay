import { Link } from "wouter";
import { Plus, Wallet as WalletIcon } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useMe } from "@/lib/auth";
import { useDisplayCurrency } from "@/lib/currency";
import {
  formatBalance,
  groupBalancesByCurrency,
  pickPrimaryBalance,
  useWallet,
} from "@/lib/wallet";

export function Header() {
  const me = useMe();
  const wallet = useWallet();
  const homeCurrency = useDisplayCurrency();
  // The pill used to live-convert every balance into the user's
  // displayCurrency and show one figure. Multi-currency wallets break
  // that — a fixed FX rate would lie. Show the user's home currency
  // first (when it has a non-zero balance), badge other non-zero
  // currencies as ``+N``.
  const grouped = groupBalancesByCurrency(wallet.data ?? []);
  const balance = pickPrimaryBalance(grouped, homeCurrency);
  const others = grouped.filter(
    (g) => g.amount !== 0 && g.currency !== balance?.currency,
  );
  const extraCount = others.length;
  const user = me.data;

  return (
    <header className="fixed top-0 left-0 right-0 h-16 bg-background/80 backdrop-blur-xl border-b border-border z-50 flex items-center justify-between px-4 max-w-[430px] mx-auto">
      {/* Brand — full wordmark SVG. Lives in apps/miniapp/public/, the
          path is unhashed because Vite passes /logo-wordmark.svg through
          as-is for public assets. ``alt`` is the brand name so screen
          readers / Telegram link previews still read "YuPay" even if the
          asset 404s. */}
      <Link href="/" className="flex items-center" aria-label="YuPay">
        <img
          src="/logo-wordmark.svg"
          alt="YuPay"
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
          className="flex items-stretch rounded-full border border-border bg-card overflow-hidden h-9"
          data-testid="header-wallet"
        >
          <Link
            href="/wallet"
            className="flex items-center gap-1.5 pl-3 pr-2"
            aria-label="Открыть кошелёк"
          >
            <WalletIcon size={12} className="text-white/40" />
            <span className="text-white font-bold text-sm tabular-nums leading-none">
              {user && balance
                ? formatBalance(balance.amount, balance.currency)
                : "—"}
            </span>
            {extraCount > 0 && (
              <span
                className="text-[10px] font-bold leading-none px-1.5 py-0.5 rounded-full"
                style={{
                  background: "hsl(var(--surface-2))",
                  color: "rgba(255,255,255,0.55)",
                }}
                aria-label={`Ещё ${extraCount.toString()} валют`}
                title={others
                  .map((g) => formatBalance(g.amount, g.currency))
                  .join(" · ")}
              >
                +{extraCount.toString()}
              </span>
            )}
          </Link>
          <Link
            href="/wallet/topup"
            className="flex items-center justify-center w-9 transition-colors"
            style={{ background: "hsl(var(--primary))", color: "#000" }}
            aria-label="Пополнить"
            data-testid="header-topup"
          >
            <Plus size={16} strokeWidth={3} />
          </Link>
        </div>

        <Link href="/settings" aria-label="Профиль">
          <Avatar className="w-9 h-9 border border-border">
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
