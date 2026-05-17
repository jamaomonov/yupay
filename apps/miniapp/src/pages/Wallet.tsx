import { useLocation } from "wouter";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  Clock,
  Gift,
  Sparkles,
  Wallet as WalletIcon,
} from "lucide-react";

import { useMe } from "@/lib/auth";
import {
  ACCOUNT_META,
  ACCOUNT_ORDER,
  formatBalance,
  type ParsedBalance,
  totalDisplayBalance,
  type UserAccountKind,
  useWallet,
} from "@/lib/wallet";

export default function Wallet() {
  const [, setLocation] = useLocation();
  const me = useMe();
  const wallet = useWallet();

  const balances = wallet.data ?? [];
  const total = totalDisplayBalance(balances);

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
            <p className="text-white/50 text-xs uppercase tracking-widest font-bold">
              Доступно к трате
            </p>
            <p className="text-white font-bold text-3xl mt-1 tabular-nums">
              {me.data ? formatBalance(total.amount, total.currency) : "—"}
            </p>
            <p className="text-white/40 text-xs mt-1.5">
              {me.data
                ? "Сумма всех счетов в основной валюте"
                : "Войдите через Telegram, чтобы увидеть баланс"}
            </p>
          </div>
        </div>

        {/* Per-account chips */}
        {me.data && (
          <div className="grid grid-cols-3 gap-2 mt-3">
            {ACCOUNT_ORDER.map((kind) => {
              const b = balances.find((x) => x.kind === kind);
              return <AccountChip key={kind} kind={kind} balance={b} />;
            })}
          </div>
        )}
      </section>

      {/* Top-up placeholder — the real flow is gated behind acquirer
          integration (Click / Payme / Uzum / SBP / Yookassa / USDT). Showing
          the form before any provider is live shipped trust loss: users
          would fill amount + card and watch a toast. */}
      {me.data && (
        <section className="mx-4 mb-5">
          <div
            className="relative rounded-3xl p-5 overflow-hidden"
            style={{
              background: "hsl(var(--surface-1))",
              border: "1.5px dashed hsl(var(--border))",
            }}
          >
            <div className="flex items-start gap-3">
              <div
                className="w-10 h-10 rounded-2xl flex items-center justify-center flex-shrink-0"
                style={{
                  background: "hsl(var(--primary) / 0.12)",
                  color: "hsl(var(--primary))",
                }}
                aria-hidden="true"
              >
                <Clock size={18} />
              </div>
              <div className="min-w-0 flex-1">
                <h2 className="text-white font-bold text-sm flex items-center gap-2">
                  Пополнение баланса
                  <span
                    className="text-[10px] uppercase tracking-[0.12em] font-bold px-2 py-0.5 rounded-full"
                    style={{
                      background: "hsl(var(--primary) / 0.18)",
                      color: "hsl(var(--primary))",
                    }}
                  >
                    скоро
                  </span>
                </h2>
                <p className="text-white/55 text-[12px] mt-1.5 leading-relaxed">
                  Подключаем Click, Payme, Uzum, СБП и USDT. До этого баланс
                  пополняется автоматически — кэшбэком за заказы и
                  реферальными бонусами.
                </p>
                <div className="mt-3 flex items-center gap-2 text-[11px] text-white/35">
                  <Sparkles size={12} className="text-primary/70" />
                  <span>Кэшбэк начисляется автоматически после доставки</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      )}
    </motion.div>
  );
}

function AccountChip({
  kind,
  balance,
}: {
  kind: UserAccountKind;
  balance: ParsedBalance | undefined;
}) {
  const meta = ACCOUNT_META[kind];
  const tone =
    meta.tone === "primary"
      ? { bg: "hsl(var(--primary) / 0.12)", fg: "hsl(var(--primary))" }
      : meta.tone === "amber"
        ? { bg: "rgba(251, 191, 36, 0.12)", fg: "rgb(252, 211, 77)" }
        : { bg: "rgba(167, 139, 250, 0.12)", fg: "rgb(196, 181, 253)" };
  const Icon = kind === "user_wallet" ? WalletIcon : kind === "user_cashback" ? Sparkles : Gift;
  const amount = balance?.amount ?? 0;
  const currency = balance?.currency ?? "USD";
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
          {currency}
        </span>
      </div>
      <p className="text-white text-base font-bold tabular-nums leading-none">
        {formatBalance(amount, currency)}
      </p>
      <p className="text-white/40 text-[10px] leading-tight line-clamp-1">{meta.label}</p>
    </div>
  );
}
