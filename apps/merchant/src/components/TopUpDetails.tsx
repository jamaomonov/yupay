"use client";

import { useTranslations } from "next-intl";

import type { P2PDeposit } from "@/lib/types";

import { CopyButton } from "@/components/CopyButton";
import { formatClock, formatSom, secondsLeft } from "@/lib/p2p";

interface TopUpDetailsProps {
  deposit: P2PDeposit;
  nowMs: number;
  locale: string;
  waiting: boolean;
  busy: boolean;
  error?: string | null;
  onCancel: () => void;
  onPaid: () => void;
}

/** The exact amount, the card and the clock — everything needed to make the transfer. */
export function TopUpDetails({
  deposit,
  nowMs,
  locale,
  waiting,
  busy,
  error = null,
  onCancel,
  onPaid,
}: TopUpDetailsProps) {
  const t = useTranslations("merchant.topUp");
  const left = secondsLeft(deposit.expires_at, nowMs);
  const amount = formatSom(deposit.amount_uzs, locale);
  // Digits only: what a banking app's field takes, whatever the grouping on screen.
  const pan = deposit.card?.pan ?? "";

  return (
    <section className="border-border bg-card mt-5 max-w-md rounded-xl border p-6">
      <p className="text-tx-dim text-xs">{t("exactAmount")}</p>
      <p className="mt-1 flex flex-wrap items-center gap-3">
        <span className="text-primary-ink font-mono text-3xl font-extrabold tabular-nums">
          {amount}
        </span>
        <CopyButton value={String(deposit.amount_uzs)} label={t("copy")} done={t("copied")} />
      </p>

      {deposit.card !== null && (
        <>
          <p className="text-tx-dim mt-5 text-xs">{t("card")}</p>
          <p className="mt-1 flex flex-wrap items-center gap-3">
            <span className="font-mono text-lg font-semibold tabular-nums">{deposit.card.pan}</span>
            <CopyButton value={pan.replace(/\D/g, "")} label={t("copy")} done={t("copied")} />
          </p>
          <p className="text-tx-dim mt-3 text-xs">{t("holder")}</p>
          <p className="mt-0.5 text-sm font-medium">{deposit.card.holder_name}</p>
        </>
      )}

      <p className="text-tx-mute mt-5 font-mono text-sm tabular-nums">
        {t("timeLeft", { time: formatClock(left) })}
      </p>
      <p className="border-border bg-card-2 mt-3 rounded-lg border p-3 text-[13px] leading-relaxed">
        {t("exactWarning", { amount })}
      </p>

      {error !== null && (
        <p role="alert" className="mt-4 text-sm text-red-500">
          {error}
        </p>
      )}
      {waiting && <p className="text-tx-mute mt-4 text-sm">{t("waiting")}</p>}
      <div className="mt-5 flex gap-3">
        <button
          type="button"
          disabled={busy}
          onClick={onCancel}
          className="border-border rounded-btn border px-4 py-2 text-sm font-semibold disabled:opacity-50"
        >
          {t("cancel")}
        </button>
        {!waiting && (
          <button
            type="button"
            onClick={onPaid}
            className="bg-primary text-primary-foreground rounded-btn px-4 py-2 text-sm font-semibold"
          >
            {t("iPaid")}
          </button>
        )}
      </div>
    </section>
  );
}
