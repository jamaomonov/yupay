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
import { useDisplayCurrency, type DisplayCurrency } from "@/lib/currency";
import { useFxRate } from "@/lib/fx";
import { useDocumentTitle } from "@/lib/use-document-title";
import {
  ACCOUNT_META,
  VISIBLE_ACCOUNT_KINDS,
  convertFromUsd,
  formatBalance,
  type ParsedBalance,
  totalDisplayBalance,
  type UserAccountKind,
  useWallet,
} from "@/lib/wallet";

export default function Wallet() {
  useDocumentTitle("Кошелёк");
  const [, setLocation] = useLocation();
  const me = useMe();
  const wallet = useWallet();
  const displayCurrency = useDisplayCurrency();
  const fx = useFxRate(displayCurrency);

  const balances = wallet.data ?? [];
  const total = totalDisplayBalance(
    balances,
    displayCurrency,
    fx.ready ? fx.rate : null,
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

      {/* Hero balance card */}
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
              Доступно к трате
            </p>
            <p className="text-white font-bold text-3xl mt-1 tabular-nums">
              {me.data && total.ready
                ? formatBalance(total.amount, total.currency)
                : "—"}
            </p>
            <p className="text-white/40 text-xs mt-1.5">
              {me.data
                ? "Сумма всех счетов в основной валюте"
                : "Войдите через Telegram, чтобы увидеть баланс"}
            </p>
          </div>
        </div>

        {/* Per-account chips — currently a single wallet card while
            cashback / promo earn flows are still off. The list collapses
            to a single full-width chip so the page doesn't look broken
            with two ghost slots. */}
        {me.data && (
          <div className="grid grid-cols-1 gap-2 mt-3">
            {VISIBLE_ACCOUNT_KINDS.map((kind) => {
              const b = balances.find((x) => x.kind === kind);
              return (
                <AccountChip
                  key={kind}
                  kind={kind}
                  balance={b}
                  displayCurrency={displayCurrency}
                  rate={fx.ready ? fx.rate : null}
                />
              );
            })}
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

function AccountChip({
  kind,
  balance,
  displayCurrency,
  rate,
}: {
  kind: UserAccountKind;
  balance: ParsedBalance | undefined;
  displayCurrency: DisplayCurrency;
  rate: number | null;
}) {
  const meta = ACCOUNT_META[kind];
  const tone =
    meta.tone === "primary"
      ? { bg: "hsl(var(--primary) / 0.12)", fg: "hsl(var(--primary))" }
      : meta.tone === "amber"
        ? { bg: "rgba(251, 191, 36, 0.12)", fg: "rgb(252, 211, 77)" }
        : { bg: "rgba(167, 139, 250, 0.12)", fg: "rgb(196, 181, 253)" };
  const Icon = WalletIcon;
  const usdAmount = balance?.amount ?? 0;
  const ready = rate !== null;
  const amount = ready ? convertFromUsd(usdAmount, rate) : 0;
  return (
    <div
      className="rounded-2xl p-3 flex flex-col gap-1.5"
      style={{
        background: "hsl(var(--surface-2))",
        border: "1px solid hsl(var(--border))",
      }}
    >
      <div className="flex items-center justify-between">
        <span
          className="w-6 h-6 rounded-lg flex items-center justify-center"
          style={{ background: tone.bg, color: tone.fg }}
        >
          <Icon size={12} />
        </span>
        <span className="text-[10px] uppercase font-bold tracking-wider text-white/40">
          {displayCurrency}
        </span>
      </div>
      <p className="text-white text-base font-bold tabular-nums leading-none">
        {ready ? formatBalance(amount, displayCurrency) : "—"}
      </p>
      <p className="text-white/40 text-[10px] leading-tight line-clamp-1">{meta.label}</p>
    </div>
  );
}
