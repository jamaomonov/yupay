import { useState } from "react";
import { useLocation } from "wouter";
import { motion } from "framer-motion";
import {
  ArrowLeft,
  Banknote,
  Bitcoin,
  CreditCard,
  Shield,
  Smartphone,
  Wallet as WalletIcon,
} from "lucide-react";

import { useToast } from "@/hooks/use-toast";
import { useMe } from "@/lib/auth";
import { useDisplayCurrency } from "@/lib/currency";
import { useDocumentTitle } from "@/lib/use-document-title";

interface ProviderOption {
  id: string;
  label: string;
  hint: string;
  Icon: typeof CreditCard;
  /** ``"live"`` providers route through real acquirers; everything else
   *  shows a "скоро" pill and the submit button keeps disabled. */
  status: "live" | "soon";
}

const PROVIDERS: ProviderOption[] = [
  { id: "click", label: "Click", hint: "UZ · карта / Humo / Uzcard", Icon: CreditCard, status: "soon" },
  { id: "payme", label: "Payme", hint: "UZ · карта", Icon: Smartphone, status: "soon" },
  { id: "uzum", label: "Uzum", hint: "UZ · Humo / Uzcard", Icon: Banknote, status: "soon" },
  { id: "sbp", label: "СБП", hint: "RU · банк-переводом", Icon: Smartphone, status: "soon" },
  { id: "yookassa", label: "YooKassa", hint: "RU · карта", Icon: CreditCard, status: "soon" },
  { id: "usdt", label: "USDT", hint: "TRC-20 / ERC-20", Icon: Bitcoin, status: "soon" },
];

const QUICK_AMOUNTS_USD = [5, 10, 25, 50, 100];

export default function WalletTopUp() {
  useDocumentTitle("Пополнение");
  const [, setLocation] = useLocation();
  const me = useMe();
  const displayCurrency = useDisplayCurrency();
  const toast = useToast();

  const [amount, setAmount] = useState("");
  const [provider, setProvider] = useState<string | null>(null);

  const numericAmount = Number.parseFloat(amount) || 0;
  const canSubmit = numericAmount > 0 && provider !== null && me.data !== undefined;
  const selectedProvider = provider
    ? PROVIDERS.find((p) => p.id === provider) ?? null
    : null;

  const onSubmit = () => {
    if (!selectedProvider) return;
    if (selectedProvider.status === "soon") {
      toast.toast({
        title: "Провайдер ещё не подключён",
        description: `${selectedProvider.label} включим как только закроем интеграцию.`,
      });
      return;
    }
    // Live providers will route here once the acquirer integration lands.
    toast.toast({
      title: "Маршрут не настроен",
      description: "Сообщите в поддержку — мы ускорим.",
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
      <div className="flex items-center justify-between px-4 pt-4 pb-3">
        <button
          type="button"
          onClick={() => { setLocation("/wallet"); }}
          className="w-9 h-9 rounded-full bg-card border border-border flex items-center justify-center"
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
            <span className="text-white/50 text-xs uppercase tracking-[0.08em] font-bold">
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
                className="bg-transparent text-white font-bold text-4xl tabular-nums outline-none w-full"
              />
              <span className="text-white/40 text-base font-bold uppercase">
                {displayCurrency}
              </span>
            </div>
          </label>
        </div>

        {/* Quick-amount chips */}
        <div className="grid grid-cols-5 gap-1.5 mt-3">
          {QUICK_AMOUNTS_USD.map((value) => {
            const active = Number.parseFloat(amount) === value;
            return (
              <button
                key={value}
                type="button"
                onClick={() => { setAmount(value.toString()); }}
                className="rounded-2xl py-2 text-sm font-bold tabular-nums transition-colors"
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
                {value}
              </button>
            );
          })}
        </div>
      </section>

      {/* Provider list */}
      <section className="mx-4 mb-5">
        <h2 className="text-white/50 text-xs uppercase tracking-[0.08em] font-bold px-1 mb-2">
          Способ оплаты
        </h2>
        <ul className="space-y-2">
          {PROVIDERS.map((p) => {
            const active = provider === p.id;
            const Icon = p.Icon;
            return (
              <li key={p.id}>
                <button
                  type="button"
                  onClick={() => { setProvider(p.id); }}
                  className="w-full rounded-2xl p-3.5 flex items-center gap-3 transition-colors"
                  style={{
                    background: active
                      ? "hsl(var(--primary) / 0.12)"
                      : "hsl(var(--surface-1))",
                    border: active
                      ? "1.5px solid hsl(var(--primary))"
                      : "1px solid hsl(var(--border))",
                  }}
                  data-testid={`provider-${p.id}`}
                >
                  <span
                    className="w-10 h-10 rounded-xl flex items-center justify-center"
                    style={{
                      background: "hsl(var(--surface-2))",
                      color: "hsl(var(--primary))",
                    }}
                    aria-hidden="true"
                  >
                    <Icon size={18} />
                  </span>
                  <span className="min-w-0 flex-1 text-left">
                    <span className="block text-white font-bold text-sm flex items-center gap-2">
                      {p.label}
                      {p.status === "soon" && (
                        <span
                          className="text-[9px] uppercase tracking-[0.08em] font-bold px-1.5 py-0.5 rounded-full"
                          style={{
                            background: "rgba(255,255,255,0.08)",
                            color: "rgba(255,255,255,0.5)",
                          }}
                        >
                          скоро
                        </span>
                      )}
                    </span>
                    <span className="block text-white/45 text-[12px] mt-0.5 truncate">
                      {p.hint}
                    </span>
                  </span>
                  <span
                    className="w-4 h-4 rounded-full flex items-center justify-center flex-shrink-0"
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
          className="w-full rounded-2xl py-3.5 font-bold text-sm transition-colors disabled:cursor-not-allowed"
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
          {canSubmit
            ? `Пополнить на ${numericAmount.toFixed(2)} ${displayCurrency}`
            : numericAmount === 0
              ? "Введите сумму"
              : "Выберите способ оплаты"}
        </button>

        <p className="mt-3 text-[11px] text-white/40 flex items-start gap-2">
          <Shield size={12} className="text-white/40 flex-shrink-0 mt-0.5" />
          <span>
            Деньги попадают на счёт <WalletIcon size={11} className="inline" />{" "}
            <strong className="text-white/60">Кошелёк</strong> — оттуда вы платите
            за заказы. Возвраты возвращаются туда же.
          </span>
        </p>
      </section>
    </motion.div>
  );
}
