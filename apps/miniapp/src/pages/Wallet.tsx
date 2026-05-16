import { useState } from "react";
import { useLocation } from "wouter";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  Bitcoin,
  Check,
  ChevronRight,
  CreditCard,
  Gift,
  Sparkles,
  Wallet as WalletIcon,
  Zap,
} from "lucide-react";

import { useToast } from "@/hooks/use-toast";
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

const PRESETS_USD = [5, 10, 25, 50, 100, 250];

const METHODS = [
  { id: "card", name: "Карта", sub: "Visa · Mastercard · МИР", icon: CreditCard },
  { id: "sbp", name: "СБП", sub: "Без комиссии", icon: Zap },
  { id: "crypto", name: "Крипта", sub: "USDT TRC-20 · ERC-20", icon: Bitcoin },
];

export default function Wallet() {
  const [, setLocation] = useLocation();
  const { toast } = useToast();
  const me = useMe();
  const wallet = useWallet();

  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState("card");

  const balances = wallet.data ?? [];
  const total = totalDisplayBalance(balances);
  const parsedAmount = Number.parseFloat(amount.replace(/\s/g, "").replace(",", "."));
  const amountValid = Number.isFinite(parsedAmount) && parsedAmount > 0;

  const onSubmit = () => {
    if (!me.data) {
      toast({
        title: "Не авторизованы",
        description: "Откройте миниапп через Telegram",
        variant: "destructive",
      });
      return;
    }
    if (!amountValid) {
      toast({
        title: "Введите сумму",
        description: "Сумма пополнения должна быть больше нуля",
        variant: "destructive",
      });
      return;
    }
    toast({
      title: "Пополнение скоро",
      description: `Идём через ${method.toUpperCase()} на $${parsedAmount.toFixed(2)}. Подключим эквайринг — заработает.`,
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: -20 }}
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
              "linear-gradient(135deg, hsl(228 32% 17%) 0%, hsl(228 32% 12%) 100%)",
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
            <p className="text-white font-black text-3xl mt-1 tabular-nums">
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

      {/* Top-up form */}
      <section className="mx-4 mb-5">
        <h2 className="text-sm font-bold text-white mb-3 flex items-center gap-2">
          <Sparkles size={14} className="text-primary" />
          Пополнить баланс
        </h2>

        {/* Amount input */}
        <div className="relative mb-3">
          <span className="absolute left-4 top-1/2 -translate-y-1/2 text-white/40 font-bold text-base">
            $
          </span>
          <input
            type="text"
            inputMode="decimal"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="0.00"
            className="w-full rounded-2xl pl-9 pr-4 py-4 text-2xl font-black text-white placeholder:text-white/15 outline-none transition-all tabular-nums"
            style={{
              background: "hsl(228 32% 17%)",
              border: amountValid
                ? "1.5px solid hsl(var(--primary) / 0.7)"
                : "1.5px solid hsl(var(--border))",
              boxShadow: amountValid ? "0 0 0 3px hsl(var(--primary) / 0.1)" : "none",
            }}
          />
        </div>

        {/* Presets */}
        <div className="grid grid-cols-3 gap-2 mb-4">
          {PRESETS_USD.map((p) => {
            const active = parsedAmount === p;
            return (
              <button
                key={p}
                onClick={() => setAmount(String(p))}
                className="rounded-2xl py-2.5 text-sm font-bold transition-all"
                style={{
                  background: active ? "hsl(var(--primary) / 0.12)" : "hsl(228 32% 16%)",
                  border: active
                    ? "1.5px solid hsl(var(--primary) / 0.7)"
                    : "1.5px solid hsl(var(--border))",
                  color: active ? "hsl(var(--primary))" : "rgba(255,255,255,0.7)",
                }}
              >
                ${p}
              </button>
            );
          })}
        </div>

        {/* Payment method */}
        <p className="text-xs uppercase tracking-widest font-bold text-white/40 mb-2">
          Способ оплаты
        </p>
        <div className="space-y-2">
          {METHODS.map((m) => {
            const active = m.id === method;
            return (
              <button
                key={m.id}
                onClick={() => setMethod(m.id)}
                className="w-full flex items-center gap-3 p-3.5 rounded-2xl text-left transition-all"
                style={{
                  background: active ? "hsl(228 32% 19%)" : "hsl(228 32% 16%)",
                  border: active
                    ? "1.5px solid hsl(var(--primary) / 0.7)"
                    : "1.5px solid hsl(var(--border))",
                }}
              >
                <div
                  className="w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0"
                  style={{
                    background: active
                      ? "hsl(var(--primary) / 0.15)"
                      : "hsl(228 32% 22%)",
                    color: active ? "hsl(var(--primary))" : "rgba(255,255,255,0.6)",
                  }}
                >
                  <m.icon size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-white font-bold text-sm">{m.name}</p>
                  <p className="text-white/40 text-[11px] mt-0.5">{m.sub}</p>
                </div>
                {active ? (
                  <div
                    className="w-5 h-5 rounded-full flex items-center justify-center"
                    style={{ background: "hsl(var(--primary))" }}
                  >
                    <Check size={11} strokeWidth={3} className="text-black" />
                  </div>
                ) : (
                  <ChevronRight size={16} className="text-white/30" />
                )}
              </button>
            );
          })}
        </div>
      </section>

      {/* CTA */}
      <div className="fixed bottom-[76px] left-1/2 -translate-x-1/2 w-full max-w-[430px] px-4 z-40">
        <motion.button
          whileTap={{ scale: 0.97 }}
          onClick={onSubmit}
          className="w-full py-4 rounded-2xl text-base font-black tracking-wide flex items-center justify-center gap-2 transition-all"
          style={{
            background: amountValid ? "hsl(var(--primary))" : "hsl(var(--primary) / 0.45)",
            color: "#000",
            boxShadow: amountValid ? "0 0 24px hsl(var(--primary) / 0.35)" : "none",
          }}
        >
          {amountValid ? `Пополнить на $${parsedAmount.toFixed(2)}` : "Введите сумму"}
          <ChevronRight size={18} strokeWidth={2.5} />
        </motion.button>
      </div>
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
        background: "hsl(228 32% 16%)",
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
      <p className="text-white text-base font-black tabular-nums leading-none">
        {formatBalance(amount, currency)}
      </p>
      <p className="text-white/40 text-[10px] leading-tight line-clamp-1">{meta.label}</p>
    </div>
  );
}
