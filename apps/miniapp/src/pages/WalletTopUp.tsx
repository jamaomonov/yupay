import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { Shield, Wallet as WalletIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useLocation } from "wouter";

import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import {
  methodVisibility,
  providerStatusMap,
  selectActiveMethodId,
  useAvailableProviders,
} from "@/lib/orders";
import { PAYMENT_METHODS, PROVIDER_BY_METHOD } from "@/lib/payment-methods";
import { openExternalLink } from "@/lib/telegram";
import { useDocumentTitle } from "@/lib/use-document-title";
import { createWalletTopUp, formatBalance } from "@/lib/wallet";

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
const DEFAULT_METHOD_ID = PAYMENT_METHODS[0]?.id ?? "click";

const MIN_AMOUNT: Record<string, number> = {
  UZS: 10_000,
  USDT: 5,
  USD: 5,
  RUB: 500,
};

export default function WalletTopUp() {
  const { t, locale } = useT();
  useDocumentTitle(t("walletTopUp.title"));
  const me = useMe();
  const toast = useToast();
  const qc = useQueryClient();
  const [, setLocation] = useLocation();

  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<string>(DEFAULT_METHOD_ID);

  // Admin-controlled provider availability (`GET /payments/providers`) — same
  // source the checkout flow (`TopUp`) reads. A slug absent from the response
  // is hidden entirely; `maintenance` is shown but locked out below.
  const providersQuery = useAvailableProviders();
  const providerStatusBySlug = useMemo(() => {
    if (!providersQuery.data) return null;
    return providerStatusMap(providersQuery.data);
  }, [providersQuery.data]);

  // Once live status lands, make sure the selection reflects it: the
  // hardcoded default (`PAYMENT_METHODS[0]`) may itself be under maintenance
  // or admin-disabled. Reselect the first active method, or clear the
  // selection entirely when none are — `canSubmit` below then keeps the
  // submit button disabled rather than ever leaving a non-active method
  // selected.
  useEffect(() => {
    if (!providerStatusBySlug) return;
    setMethod(
      (current) => selectActiveMethodId(PAYMENT_METHODS, current, providerStatusBySlug) ?? "",
    );
  }, [providerStatusBySlug]);

  const selectedMethod = PAYMENT_METHODS.find((m) => m.id === method) ?? PAYMENT_METHODS[0]!;
  const currency = selectedMethod.currency;
  const quickAmounts = QUICK_AMOUNTS[currency] ?? QUICK_AMOUNTS.USD!;

  const numericAmount = Number.parseFloat(amount) || 0;
  const minAmount = MIN_AMOUNT[currency] ?? MIN_AMOUNT.USD!;
  const amountOk = numericAmount >= minAmount;
  const canSubmit = amountOk && me.data !== undefined && method !== "";

  // Switching methods between different currencies (UZS → USDT) would leave a
  // stale amount in the wrong context. Clearing on currency change avoids the
  // "пополнить на 50 000 USDT" confusion.
  const onMethodChange = (next: (typeof PAYMENT_METHODS)[number]) => {
    if (methodVisibility(next.provider, providerStatusBySlug) !== "active") return;
    if (next.currency !== currency) {
      setAmount("");
    }
    setMethod(next.id);
  };

  const topup = useMutation({
    mutationFn: async () => {
      const provider = PROVIDER_BY_METHOD[method];
      if (!provider) {
        throw new Error("missing provider");
      }
      return createWalletTopUp(numericAmount, provider);
    },
    onSuccess: (payment) => {
      void qc.invalidateQueries({ queryKey: ["wallet"] });
      if (payment.intent_url && payment.provider !== "mock") {
        toast.toast({ title: t("walletTopUp.redirecting") });
        openExternalLink(payment.intent_url);
      }
      setLocation(`/order/${payment.order_id}`);
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? err.detail : t("walletTopUp.failed");
      toast.toast({ title: t("walletTopUp.failed"), description: detail, variant: "destructive" });
    },
  });

  const onSubmit = () => {
    if (!canSubmit || topup.isPending) return;
    topup.mutate();
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
        {/* No in-page back arrow: Telegram's own BackButton is already shown
            on this route and pops real history, while this one jumped to a
            fixed destination — two arrows, two different results. */}
        <h1 className="text-base font-bold text-white">{t("walletTopUp.title")}</h1>
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
              {t("walletTopUp.amountLabel")}
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
                {currency === "UZS" ? value.toLocaleString(locale) : value.toString()}
              </button>
            );
          })}
        </div>
      </section>

      {/* Provider list */}
      <section className="mx-4 mb-5">
        <h2 className="mb-2 px-1 text-xs font-bold uppercase tracking-[0.08em] text-white/50">
          {t("walletTopUp.method")}
        </h2>
        <ul className="space-y-2">
          {PAYMENT_METHODS.map((m) => {
            // Absent from the providers response → admin-disabled, not
            // offered at all — distinct from `maintenance`, which is still
            // rendered but locked out (non-clickable) below.
            const visibility = methodVisibility(m.provider, providerStatusBySlug);
            if (visibility === "hidden") return null;
            const maintenance = visibility === "maintenance";
            const active = method === m.id && !maintenance;
            return (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => {
                    onMethodChange(m);
                  }}
                  disabled={maintenance}
                  aria-disabled={maintenance}
                  className="flex w-full items-center gap-3 rounded-2xl p-3.5 transition-colors disabled:cursor-not-allowed"
                  style={{
                    background: active ? "hsl(var(--primary) / 0.12)" : "hsl(var(--surface-1))",
                    border: active
                      ? "1.5px solid hsl(var(--primary))"
                      : "1px solid hsl(var(--border))",
                    opacity: maintenance ? 0.5 : 1,
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
                    <span className="mt-0.5 block truncate text-[12px] text-white/45">
                      {maintenance ? t("payment.maintenance") : t(m.subKey)}
                    </span>
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
          disabled={!canSubmit || topup.isPending}
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
          {topup.isPending
            ? t("walletTopUp.processing")
            : canSubmit
              ? t("walletTopUp.submit", { amount: formatBalance(numericAmount, currency) })
              : numericAmount > 0 && !amountOk
                ? t("walletTopUp.minAmount", { amount: formatBalance(minAmount, currency) })
                : t("walletTopUp.enterAmount")}
        </button>

        <p className="mt-3 flex items-start gap-2 text-[11px] text-white/40">
          <Shield size={12} className="mt-0.5 flex-shrink-0 text-white/40" />
          <span>
            {t("walletTopUp.disclaimerBefore")} <WalletIcon size={11} className="inline" />{" "}
            <strong className="text-white/60">{t("walletTopUp.walletName")}</strong>{" "}
            {t("walletTopUp.disclaimerAfter")}
          </span>
        </p>
      </section>
    </motion.div>
  );
}
