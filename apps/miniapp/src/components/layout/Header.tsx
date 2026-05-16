import { Link } from "wouter";
import { Plus, Wallet as WalletIcon } from "lucide-react";

import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useMe } from "@/lib/auth";
import {
  formatBalance,
  totalDisplayBalance,
  useWallet,
} from "@/lib/wallet";

export function Header() {
  const me = useMe();
  const wallet = useWallet();
  const balance = totalDisplayBalance(wallet.data ?? []);
  const user = me.data;

  return (
    <header className="fixed top-0 left-0 right-0 h-16 bg-background/80 backdrop-blur-xl border-b border-border z-50 flex items-center justify-between px-4 max-w-[430px] mx-auto">
      {/* Brand */}
      <Link href="/" className="flex items-center gap-2">
        <div
          className="w-8 h-8 rounded-xl flex items-center justify-center"
          style={{
            background: "hsl(var(--primary) / 0.15)",
            color: "hsl(var(--primary))",
          }}
        >
          <WalletIcon size={16} strokeWidth={2.4} />
        </div>
        <span className="font-black tracking-wider text-lg text-white">
          YUPAY
        </span>
      </Link>

      {/* Balance pill + top-up + avatar */}
      <div className="flex items-center gap-2">
        <Link
          href="/wallet"
          className="flex items-stretch rounded-full border border-border bg-card overflow-hidden h-9"
          data-testid="header-wallet"
        >
          <div className="flex items-center gap-1.5 pl-3 pr-2">
            <WalletIcon size={12} className="text-white/40" />
            <span className="text-white font-bold text-sm tabular-nums leading-none">
              {user ? formatBalance(balance.amount, balance.currency) : "—"}
            </span>
          </div>
          <div
            className="flex items-center justify-center w-9 transition-colors"
            style={{ background: "hsl(var(--primary))", color: "#000" }}
            aria-label="Пополнить"
          >
            <Plus size={16} strokeWidth={3} />
          </div>
        </Link>

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
            <AvatarFallback className="bg-primary/20 text-primary text-xs font-black">
              {(user?.display_name?.[0] ?? "?").toUpperCase()}
            </AvatarFallback>
          </Avatar>
        </Link>
      </div>
    </header>
  );
}
