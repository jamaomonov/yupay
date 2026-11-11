"use client";

import { useTranslations } from "next-intl";

import { formatRate, formatSom, usdPreview } from "@/lib/p2p";

interface CardAmountFormProps {
  /** Bare digits, as typed. */
  amount: string;
  onAmount: (digits: string) => void;
  fxRate: string | null;
  locale: string;
  busy: boolean;
  error: string | null;
  onSubmit: () => void;
  onBack: () => void;
}

/** The card top-up's amount in soʻm, with the USD it will become. */
export function CardAmountForm({
  amount,
  onAmount,
  fxRate,
  locale,
  busy,
  error,
  onSubmit,
  onBack,
}: CardAmountFormProps) {
  const t = useTranslations("merchant.topUp");
  const value = Number(amount);
  const preview = usdPreview(value, fxRate);

  return (
    <form
      className="border-border bg-card mt-5 max-w-md rounded-xl border p-6"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <button
        type="button"
        onClick={onBack}
        className="text-tx-mute mb-3 text-sm underline-offset-4 hover:underline"
      >
        ← {t("changeMethod")}
      </button>
      <label className="text-tx-dim block text-xs" htmlFor="topup-amount">
        {t("amountLabel")}
      </label>
      <input
        id="topup-amount"
        inputMode="numeric"
        autoComplete="off"
        value={amount === "" ? "" : formatSom(value, locale)}
        onChange={(event) => {
          // Digits only, grouped on display («50 000»); state keeps bare digits.
          onAmount(event.target.value.replace(/\D/g, "").slice(0, 10));
        }}
        className="border-border bg-card-2 rounded-btn mt-1.5 block w-full border px-3 py-2 font-mono text-lg"
      />
      {preview !== null && (
        <p className="text-tx-mute mt-2 text-sm">
          {t("usdPreview", { usd: preview, rate: formatRate(fxRate ?? "", locale) })}
        </p>
      )}
      {error !== null && (
        <p role="alert" className="mt-3 text-sm text-red-500">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={busy || !(value > 0)}
        className="bg-primary text-primary-foreground rounded-btn mt-4 px-4 py-2 text-sm font-semibold disabled:opacity-50"
      >
        {t("continue")}
      </button>
    </form>
  );
}
