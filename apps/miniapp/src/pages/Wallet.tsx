import { useLocation } from "wouter";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  ChevronRight,
  Plus,
  Wallet as WalletIcon,
} from "lucide-react";

import { useMe } from "@/lib/auth";
import { useDisplayCurrency } from "@/lib/currency";
import { useDocumentTitle } from "@/lib/use-document-title";
import {
  type CurrencyBalance,
  formatBalance,
  groupBalancesByCurrency,
  pickPrimaryBalance,
  useWallet,
} from "@/lib/wallet";

export default function Wallet() {
  useDocumentTitle("Кошелёк");
  const [, setLocation] = useLocation();
  const me = useMe();
  const wallet = useWallet();

  const balances = wallet.data ?? [];
  const homeCurrency = useDisplayCurrency();
  // Each currency the user holds gets its own row / chip. No more
  // live-rate conversion — 5 USD stays 5 USD whether Click's UZS rate
  // moved overnight or not. Primary is the user's home currency when
  // it has a non-zero balance; otherwise the biggest non-zero balance.
  const grouped = groupBalancesByCurrency(balances);
  const primary = pickPrimaryBalance(grouped, homeCurrency);
  // Other currencies go into a list below the hero. Drop zero rows
  // and the headline itself so we don't duplicate it.
  const others = grouped.filter(
    (g) => g.amount !== 0 && g.currency !== primary?.currency,
  );

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="pb-28"
    >
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 pt-4 pb-3">
        <button
          onClick={() => setLocation("/")}
          className="w-9 h-9 rounded-full bg-card border border-border flex items-center justify-center"
          aria-label="Назад"
        >
          <ArrowLeft size={16} className="text-white/70" />
        </button>
        <h1 className="text-base font-bold text-white">Кошелёк</h1>
        <div className="w-9" />
      </div>

      {!me.data && !me.isLoading && (
        <div className="mx-4 mb-4 rounded-2xl border border-yellow-400/30 bg-yellow-400/5 p-4 flex items-start gap-3">
          <AlertTriangle size={18} className="text-yellow-400 flex-shrink-0 mt-0.5" />
          <div className="text-sm">
            <p className="font-semibold text-yellow-200">Откройте в Telegram</p>
            <p className="text-yellow-100/70 text-xs mt-1">
              Баланс и пополнение доступны после авторизации.
            </p>
          </div>
        </div>
      )}

      {/* Hero balance card. With multi-currency wallets the hero shows
          the first currency big, then the rest as smaller chips below.
          One currency = clean hero; several = honest split. */}
      <section className="mx-4 mb-5">
        <div
          className="relative rounded-3xl p-5 overflow-hidden"
          style={{
            background:
              "linear-gradient(135deg, hsl(var(--surface-2)) 0%, hsl(var(--background)) 100%)",
            border: "1px solid hsl(var(--border))",
          }}
        >
          <div
            className="absolute -top-20 -right-20 w-56 h-56 rounded-full pointer-events-none"
            style={{
              background:
                "radial-gradient(circle, hsl(var(--primary) / 0.22) 0%, transparent 70%)",
            }}
          />
          <div className="relative z-10">
            <p className="text-white/50 text-xs uppercase tracking-[0.08em] font-bold">
              На балансе
            </p>
            <p className="text-white font-bold text-3xl mt-1 tabular-nums">
              {!me.data
                ? "—"
                : formatBalance(primary?.amount ?? 0, primary?.currency ?? homeCurrency)}
            </p>
            <p className="text-white/40 text-xs mt-1.5">
              {me.data
                ? "Баланс показывается в валюте счёта"
                : "Войдите через Telegram, чтобы увидеть баланс"}
            </p>
          </div>
        </div>

        {/* Additional non-zero currencies stack below the hero. Empty
            accounts are intentionally skipped — a row of "$0.00" next
            to a real UZS balance reads as a bug. */}
        {me.data && others.length > 0 && (
          <div className="grid grid-cols-1 gap-2 mt-3">
            {others.map((g) => (
              <CurrencyChip key={g.currency} group={g} />
            ))}
          </div>
        )}
      </section>

      {/* Primary action: top up. CTA tile instead of a dashed placeholder
          so the page feels like a finished tool — the form behind it can
          ship in stages without forcing the user to look at a "скоро"
          notice every time they open the wallet. */}
      {me.data && (
        <section className="mx-4 mb-5">
          <button
            type="button"
            onClick={() => { setLocation("/wallet/topup"); }}
            className="w-full rounded-3xl p-4 flex items-center gap-3 active:scale-[0.99] transition-transform"
            style={{
              background: "hsl(var(--primary))",
              color: "#000",
            }}
            data-testid="wallet-topup-cta"
          >
            <span
              className="w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0"
              style={{ background: "rgba(0,0,0,0.12)" }}
              aria-hidden="true"
            >
              <Plus size={18} strokeWidth={3} />
            </span>
            <span className="min-w-0 flex-1 text-left">
              <span className="block font-bold text-sm">Пополнить кошелёк</span>
              <span className="block text-[12px] opacity-70 mt-0.5">
                Click · Payme · Uzum · СБП · USDT
              </span>
            </span>
            <ArrowRight size={18} strokeWidth={2.5} aria-hidden="true" />
          </button>
        </section>
      )}

      {/* History moved to /history (split into Orders / Finance tabs).
          Link gives the operator a single jump from the balance view. */}
      {me.data && (
        <section className="mx-4 mb-5">
          <button
            type="button"
            onClick={() => { setLocation("/history"); }}
            className="w-full rounded-2xl p-3.5 flex items-center gap-3 active:scale-[0.99] transition-transform"
            style={{
              background: "hsl(var(--surface-1))",
              border: "1px solid hsl(var(--border))",
            }}
          >
            <span className="min-w-0 flex-1 text-left">
              <span className="block text-white font-medium text-sm">
                История операций
              </span>
              <span className="block text-white/45 text-[12px] mt-0.5">
                Заказы и движения по балансу
              </span>
            </span>
            <ChevronRight size={16} className="text-white/40" aria-hidden="true" />
          </button>
        </section>
      )}
    </motion.div>
  );
}

function CurrencyChip({ group }: { group: CurrencyBalance }) {
  return (
    <div
      className="rounded-2xl px-4 py-3 flex items-center justify-between"
      style={{
        background: "hsl(var(--surface-2))",
        border: "1px solid hsl(var(--border))",
      }}
    >
      <span className="flex items-center gap-2">
        <span
          className="w-6 h-6 rounded-lg flex items-center justify-center"
          style={{
            background: "hsl(var(--primary) / 0.12)",
            color: "hsl(var(--primary))",
          }}
          aria-hidden="true"
        >
          <WalletIcon size={12} />
        </span>
        <span className="text-[10px] uppercase font-bold tracking-wider text-white/40">
          {group.currency}
        </span>
      </span>
      <span className="text-white text-base font-bold tabular-nums leading-none">
        {formatBalance(group.amount, group.currency)}
      </span>
    </div>
  );
}
