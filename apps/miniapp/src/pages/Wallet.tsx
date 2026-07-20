import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  ChevronRight,
  Plus,
  Ticket,
  Wallet as WalletIcon,
} from "lucide-react";
import { useState } from "react";
import { useLocation } from "wouter";

import { useToast } from "@/hooks/use-toast";
import { apiPost, newIdempotencyKey } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useDisplayCurrency } from "@/lib/currency";
import { useT } from "@/lib/i18n";
import { promoErrorKey } from "@/lib/promo";
import { useDocumentTitle } from "@/lib/use-document-title";
import {
  type CurrencyBalance,
  formatBalance,
  groupBalancesByCurrency,
  pickPrimaryBalance,
  useWallet,
} from "@/lib/wallet";

export default function Wallet() {
  const { t } = useT();
  useDocumentTitle(t("wallet.docTitle"));
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
  const others = grouped.filter((g) => g.amount !== 0 && g.currency !== primary?.currency);

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
          onClick={() => {
            setLocation("/");
          }}
          className="bg-card border-border flex h-9 w-9 items-center justify-center rounded-full border"
          aria-label={t("common.back")}
        >
          <ArrowLeft size={16} className="text-white/70" />
        </button>
        <h1 className="text-base font-bold text-white">{t("wallet.title")}</h1>
        <div className="w-9" />
      </div>

      {!me.data && !me.isLoading && (
        <div className="mx-4 mb-4 flex items-start gap-3 rounded-2xl border border-yellow-400/30 bg-yellow-400/5 p-4">
          <AlertTriangle size={18} className="mt-0.5 flex-shrink-0 text-yellow-400" />
          <div className="text-sm">
            <p className="font-semibold text-yellow-200">{t("wallet.openInTgTitle")}</p>
            <p className="mt-1 text-xs text-yellow-100/70">{t("wallet.authHint")}</p>
          </div>
        </div>
      )}

      {/* Hero balance card. With multi-currency wallets the hero shows
          the first currency big, then the rest as smaller chips below.
          One currency = clean hero; several = honest split. */}
      <section className="mx-4 mb-5">
        <div
          className="relative overflow-hidden rounded-3xl p-5"
          style={{
            background:
              "linear-gradient(135deg, hsl(var(--surface-2)) 0%, hsl(var(--background)) 100%)",
            border: "1px solid hsl(var(--border))",
          }}
        >
          <div
            className="pointer-events-none absolute -right-20 -top-20 h-56 w-56 rounded-full"
            style={{
              background: "radial-gradient(circle, hsl(var(--primary) / 0.22) 0%, transparent 70%)",
            }}
          />
          <div className="relative z-10">
            <p className="text-xs font-bold uppercase tracking-[0.08em] text-white/50">
              {t("wallet.onBalance")}
            </p>
            <p className="mt-1 text-3xl font-bold tabular-nums text-white">
              {!me.data
                ? "—"
                : formatBalance(primary?.amount ?? 0, primary?.currency ?? homeCurrency)}
            </p>
            <p className="mt-1.5 text-xs text-white/40">
              {me.data ? t("wallet.balanceInCurrency") : t("wallet.loginToSee")}
            </p>
          </div>
        </div>

        {/* Additional non-zero currencies stack below the hero. Empty
            accounts are intentionally skipped — a row of "$0.00" next
            to a real UZS balance reads as a bug. */}
        {me.data && others.length > 0 && (
          <div className="mt-3 grid grid-cols-1 gap-2">
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
            onClick={() => {
              setLocation("/wallet/topup");
            }}
            className="flex w-full items-center gap-3 rounded-3xl p-4 transition-transform active:scale-[0.99]"
            style={{
              background: "hsl(var(--primary))",
              color: "#000",
            }}
            data-testid="wallet-topup-cta"
          >
            <span
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-2xl"
              style={{ background: "rgba(0,0,0,0.12)" }}
              aria-hidden="true"
            >
              <Plus size={18} strokeWidth={3} />
            </span>
            <span className="min-w-0 flex-1 text-left">
              <span className="block text-sm font-bold">{t("wallet.topUpCta")}</span>
              <span className="mt-0.5 block text-[12px] opacity-70">{t("wallet.methods")}</span>
            </span>
            <ArrowRight size={18} strokeWidth={2.5} aria-hidden="true" />
          </button>
        </section>
      )}

      {/* Promo code: the cheapest gift rail we have — credits user_wallet
          directly, so the money shows up in the hero card above instantly. */}
      {me.data && <PromoCodeCard />}

      {/* History moved to /history (split into Orders / Finance tabs).
          Link gives the operator a single jump from the balance view. */}
      {me.data && (
        <section className="mx-4 mb-5">
          <button
            type="button"
            onClick={() => {
              setLocation("/history");
            }}
            className="flex w-full items-center gap-3 rounded-2xl p-3.5 transition-transform active:scale-[0.99]"
            style={{
              background: "hsl(var(--surface-1))",
              border: "1px solid hsl(var(--border))",
            }}
          >
            <span className="min-w-0 flex-1 text-left">
              <span className="block text-sm font-medium text-white">
                {t("wallet.historyTitle")}
              </span>
              <span className="mt-0.5 block text-[12px] text-white/45">
                {t("wallet.historySubtitle")}
              </span>
            </span>
            <ChevronRight size={16} className="text-white/40" aria-hidden="true" />
          </button>
        </section>
      )}
    </motion.div>
  );
}

interface PromoRedeemOut {
  code: string;
  amount: string;
  currency: string;
}

function PromoCodeCard() {
  const { t } = useT();
  const qc = useQueryClient();
  const { toast } = useToast();
  const [code, setCode] = useState("");

  const redeem = useMutation<PromoRedeemOut, Error, string>({
    mutationFn: (value) =>
      apiPost<PromoRedeemOut>(
        "/api/v1/promo/redeem",
        { code: value },
        { idempotencyKey: newIdempotencyKey("promo") },
      ),
    onSuccess: (data) => {
      setCode("");
      toast({ title: t("wallet.promoSuccess", { amount: `${data.amount} ${data.currency}` }) });
      // The hero balance card sits right above — refresh it immediately.
      void qc.invalidateQueries({ queryKey: ["wallet"] });
    },
    onError: (err) => {
      toast({ title: t(promoErrorKey(err)), variant: "destructive" });
    },
  });

  const trimmed = code.trim();
  const submit = () => {
    if (!trimmed || redeem.isPending) return;
    redeem.mutate(trimmed);
  };

  return (
    <section className="mx-4 mb-5">
      <div
        className="rounded-2xl p-3.5"
        style={{ background: "hsl(var(--surface-1))", border: "1px solid hsl(var(--border))" }}
      >
        <div className="mb-2.5 flex items-center gap-2">
          <Ticket size={14} style={{ color: "hsl(var(--primary))" }} aria-hidden="true" />
          <span className="text-sm font-medium text-white">{t("wallet.promoTitle")}</span>
        </div>
        <div className="flex gap-2">
          <input
            value={code}
            onChange={(e) => {
              setCode(e.target.value);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") submit();
            }}
            placeholder={t("wallet.promoPlaceholder")}
            autoCapitalize="characters"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="send"
            className="placeholder:text-body-faint min-w-0 flex-1 rounded-xl px-3.5 py-2.5 text-sm font-semibold uppercase tracking-wide text-white outline-none"
            style={{
              background: "hsl(var(--surface-2))",
              border: "1px solid hsl(var(--border))",
            }}
            data-testid="promo-input"
          />
          <button
            type="button"
            onClick={submit}
            disabled={!trimmed || redeem.isPending}
            className="flex-shrink-0 rounded-xl px-4 text-sm font-bold transition-opacity disabled:opacity-40"
            style={{ background: "hsl(var(--primary))", color: "#000" }}
            data-testid="promo-apply"
          >
            {t("wallet.promoApply")}
          </button>
        </div>
      </div>
    </section>
  );
}

function CurrencyChip({ group }: { group: CurrencyBalance }) {
  return (
    <div
      className="flex items-center justify-between rounded-2xl px-4 py-3"
      style={{
        background: "hsl(var(--surface-2))",
        border: "1px solid hsl(var(--border))",
      }}
    >
      <span className="flex items-center gap-2">
        <span
          className="flex h-6 w-6 items-center justify-center rounded-lg"
          style={{
            background: "hsl(var(--primary) / 0.12)",
            color: "hsl(var(--primary))",
          }}
          aria-hidden="true"
        >
          <WalletIcon size={12} />
        </span>
        <span className="text-[10px] font-bold uppercase tracking-wider text-white/40">
          {group.currency}
        </span>
      </span>
      <span className="text-base font-bold tabular-nums leading-none text-white">
        {formatBalance(group.amount, group.currency)}
      </span>
    </div>
  );
}
