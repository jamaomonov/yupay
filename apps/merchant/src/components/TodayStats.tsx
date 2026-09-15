"use client";

import { useTranslations } from "next-intl";

import type { Summary } from "@/lib/types";

import { formatUsd, toCents } from "@/lib/money";

/**
 * Today's three numbers: orders placed, how many of them worked, what they
 * cost.
 *
 * Shared between Orders and the dashboard. They lived only on Orders, which
 * left the dashboard — the screen a reseller opens first — with a heading that
 * repeats their own company name and a single link. Duplicating one cheap
 * `GET /summary` is a better trade than a dashboard with nothing on it.
 */
export function TodayStats({ today, balance }: { today: Summary | null; balance?: string }) {
  const t = useTranslations("merchant.orders");
  const tCabinet = useTranslations("merchant.cabinet");

  return (
    <dl className={`grid gap-3.5 ${balance === undefined ? "grid-cols-3" : "sm:grid-cols-4"}`}>
      {balance !== undefined && <Stat value={balance} label={tCabinet("balance")} accent />}
      <Stat value={today === null ? "—" : String(today.orders)} label={t("statToday")} />
      <Stat value={successRate(today)} label={t("statSuccess")} hint={t("statSuccessHint")} />
      <Stat
        value={
          today === null
            ? "—"
            : `$${formatUsd(toCents(today.spend_usd))}${today.spend_capped ? "+" : ""}`
        }
        label={t("statSpend")}
      />
    </dl>
  );
}

/** Delivered as a share of everything that finished. Open orders do not count. */
export function successRate(today: Summary | null): string {
  if (today === null) return "—";
  const finished = today.delivered + today.failed;
  return finished === 0 ? "—" : `${String(Math.round((today.delivered / finished) * 100))}%`;
}

function Stat({
  value,
  label,
  hint,
  accent,
}: {
  value: string;
  label: string;
  hint?: string;
  accent?: boolean;
}) {
  return (
    // `dt` first and `dd` second, as a definition list requires, with the
    // visual order flipped in CSS — the number reads first on screen, but the
    // markup pairs the term with its value. The hint sits inside the `dd`:
    // a loose `<p>` is not allowed in a `dl` group at all.
    <div className="border-border bg-card flex flex-col-reverse rounded-xl border px-4 py-4 sm:px-5">
      <dt className="text-tx-dim mt-1 text-xs sm:text-[12.5px]">{label}</dt>
      <dd
        className={`font-mono text-xl font-extrabold sm:text-2xl ${accent ? "text-primary-ink" : ""}`}
      >
        {value}
        {hint !== undefined && (
          <span className="text-tx-dim mt-0.5 block font-sans text-[11px] font-normal">{hint}</span>
        )}
      </dd>
    </div>
  );
}
