import { motion } from "framer-motion";
import { ArrowLeft, Shield, Wallet as WalletIcon } from "lucide-react";
import { useState } from "react";
import { useLocation } from "wouter";

import { useToast } from "@/hooks/use-toast";
import { useMe } from "@/lib/auth";
import { PAYMENT_METHODS } from "@/lib/payment-methods";
import { useDocumentTitle } from "@/lib/use-document-title";
import { formatBalance } from "@/lib/wallet";

/**
 * Quick-amount chips per currency. The shape is "round numbers a
 * customer would actually transfer" — 50 000 UZS is one tap, but
 * 50 USD is a different round number. RUB sits between the two; USDT
 * tracks USD.
 */
const QUICK_AMOUNTS: Record<string, number[]> = {
  UZS: [50_000, 100_000, 250_000, 500_000, 1_000_000],
  USD: [5, 10, 25, 50, 100],
  USDT: [5, 10, 25, 50, 100],
  RUB: [500, 1_000, 2_500, 5_000, 10_000],
};

/** Default method — kicks in on first mount so the input has an
 *  unambiguous currency before the user has touched the list. */
const DEFAULT_METHOD_ID = PAYMENT_METHODS[0]?.id ?? "inpay";

export default function WalletTopUp() {
  useDocumentTitle("Пополнение");
  const [, setLocation] = useLocation();
  const me = useMe();
  const toast = useToast();

  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<string>(DEFAULT_METHOD_ID);

  const selectedMethod = PAYMENT_METHODS.find((m) => m.id === method) ?? PAYMENT_METHODS[0]!;
  const currency = selectedMethod.currency;
  const quickAmounts = QUICK_AMOUNTS[currency] ?? QUICK_AMOUNTS.USD!;

  const numericAmount = Number.parseFloat(amount) || 0;
  const canSubmit = numericAmount > 0 && me.data !== undefined;

  // Switching methods between different currencies (UZS → USDT) would leave a
  // stale amount in the wrong context. Clearing on currency change avoids the
  // "пополнить на 50 000 USDT" confusion.
  const onMethodChange = (next: (typeof PAYMENT_METHODS)[number]) => {
    if (next.currency !== currency) {
      setAmount("");
    }
    setMethod(next.id);
  };

  const onSubmit = () => {
    // Wallet funding has no backend yet — order checkout already pays via these
    // acquirers, but crediting the wallet balance is a separate flow.
    toast.toast({
      title: "Пополнение скоро",
      description: "Скоро можно будет пополнять баланс кошелька напрямую.",
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.22 }}
      className="pb-28"
    >
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 pb-3 pt-4">
        <button
          type="button"
          onClick={() => {
            setLocation("/wallet");
          }}
          className="bg-card border-border flex h-9 w-9 items-center justify-center rounded-full border"
          aria-label="Назад к кошельку"
        >
          <ArrowLeft size={16} className="text-white/70" />
        </button>
        <h1 className="text-base font-bold text-white">Пополнение</h1>
        <div className="w-9" />
      </div>

      {/* Amount card */}
      <section className="mx-4 mb-5">
        <div
          className="rounded-3xl p-5"
          style={{
            background: "hsl(var(--surface-1))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          <label className="block">
            <span className="text-xs font-bold uppercase tracking-[0.08em] text-white/50">
              Сумма пополнения
            </span>
            <div className="mt-2 flex items-baseline gap-2">
              <input
                inputMode="decimal"
                value={amount}
                onChange={(e) => {
                  // Keep only digits + a single decimal separator so the
                  // controlled value never wedges the page (a stray "abc"
                  // used to make every chip disabled).
                  const v = e.target.value.replace(/[^\d.,]/g, "").replace(",", ".");
                  setAmount(v);
                }}
                placeholder="0"
                className="w-full bg-transparent text-4xl font-bold tabular-nums text-white outline-none"
              />
              <span className="text-base font-bold uppercase text-white/40">{currency}</span>
            </div>
          </label>
        </div>

        {/* Quick-amount chips — labels change with the provider's
            currency (50 000 UZS ↔ 50 USD ↔ 500 RUB). */}
        <div className="mt-3 grid grid-cols-5 gap-1.5">
          {quickAmounts.map((value) => {
            const active = Number.parseFloat(amount) === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => {
                  setAmount(value.toString());
                }}
                className="rounded-2xl py-2 text-[12px] font-bold tabular-nums transition-colors"
                style={
                  active
                    ? { background: "hsl(var(--primary))", color: "#000" }
                    : {
                        background: "hsl(var(--surface-1))",
                        border: "1px solid hsl(var(--border))",
                        color: "rgba(255,255,255,0.8)",
                      }
                }
              >
                {currency === "UZS" ? value.toLocaleString("ru-RU") : value.toString()}
              </button>
            );
          })}
        </div>
      </section>

      {/* Provider list */}
      <section className="mx-4 mb-5">
        <h2 className="mb-2 px-1 text-xs font-bold uppercase tracking-[0.08em] text-white/50">
          Способ оплаты
        </h2>
        <ul className="space-y-2">
          {PAYMENT_METHODS.map((m) => {
            const active = method === m.id;
            return (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => {
                    onMethodChange(m);
                  }}
                  className="flex w-full items-center gap-3 rounded-2xl p-3.5 transition-colors"
                  style={{
                    background: active ? "hsl(var(--primary) / 0.12)" : "hsl(var(--surface-1))",
                    border: active
                      ? "1.5px solid hsl(var(--primary))"
                      : "1px solid hsl(var(--border))",
                  }}
                  data-testid={`provider-${m.id}`}
                >
                  <span
                    className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-xl bg-white"
                    aria-hidden="true"
                  >
                    <img src={m.icon} alt={m.name} className="h-full w-full object-contain p-1.5" />
                  </span>
                  <span className="min-w-0 flex-1 text-left">
                    <span className="flex items-center gap-2 text-sm font-bold text-white">
                      {m.name}
                      <span
                        className="rounded-full px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[0.08em]"
                        style={{
                          background: "hsl(var(--surface-2))",
                          color: "rgba(255,255,255,0.55)",
                        }}
                      >
                        {m.currency}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-[12px] text-white/45">{m.sub}</span>
                  </span>
                  <span
                    className="flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-full"
                    style={{
                      border: active
                        ? "5px solid hsl(var(--primary))"
                        : "1.5px solid hsl(var(--border))",
                    }}
                    aria-hidden="true"
                  />
                </button>
              </li>
            );
          })}
        </ul>
      </section>

      {/* Submit */}
      <section className="mx-4 mb-5">
        <button
          type="button"
          onClick={onSubmit}
          disabled={!canSubmit}
          className="w-full rounded-2xl py-3.5 text-sm font-bold transition-colors disabled:cursor-not-allowed"
          style={
            canSubmit
              ? { background: "hsl(var(--primary))", color: "#000" }
              : {
                  background: "hsl(var(--surface-1))",
                  color: "rgba(255,255,255,0.35)",
                  border: "1px solid hsl(var(--border))",
                }
          }
        >
          {canSubmit ? `Пополнить на ${formatBalance(numericAmount, currency)}` : "Введите сумму"}
        </button>

        <p className="mt-3 flex items-start gap-2 text-[11px] text-white/40">
          <Shield size={12} className="mt-0.5 flex-shrink-0 text-white/40" />
          <span>
            Деньги попадают на счёт <WalletIcon size={11} className="inline" />{" "}
            <strong className="text-white/60">Кошелёк</strong> в той же валюте, которой вы платите.
            Возвраты возвращаются туда же.
          </span>
        </p>
      </section>
    </motion.div>
  );
}
