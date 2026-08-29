"use client";

import { useLocale, useTranslations } from "next-intl";

import { StatCard } from "@/components/panel/StatCard";
import { formatMoney } from "@/lib/money";
import { type Period, useBalance, useStats } from "@/lib/panel";

/** Each window and the key that names it. Spelled out rather than derived
 *  from the period string, so the message keys stay greppable and no cast is
 *  needed to satisfy next-intl's key typing. */
const PERIODS: { period: Period; key: string }[] = [
  { period: "day", key: "periodDay" },
  { period: "week", key: "periodWeek" },
  { period: "month", key: "periodMonth" },
  { period: "year", key: "periodYear" },
];

export default function OverviewPage() {
  const t = useTranslations("partners.panel");
  const locale = useLocale();
  const balance = useBalance();
  // One hook per window rather than a loop: hooks cannot be called
  // conditionally or in a variable-length loop, and four is not enough to
  // justify a nested component.
  const day = useStats("day");
  const week = useStats("week");
  const month = useStats("month");
  const year = useStats("year");
  const byPeriod = { day, week, month, year };

  const money = (raw: string | undefined, currency = "UZS"): string =>
    formatMoney(raw ?? "0", currency, locale);

  // Not `space-y-10`: two ruled grids, each with its own top and bottom rule,
  // left a gap bounded by two lines — which on a phone read as an empty table
  // row. They now share the single rule between them.
  return (
    <div className="space-y-px">
      <section className="grid-ruled grid grid-cols-1 sm:grid-cols-3">
        <StatCard
          label={t("available")}
          value={money(balance.data?.available, balance.data?.currency)}
          accent
        />
        <StatCard
          label={t("held")}
          value={money(balance.data?.held, balance.data?.currency)}
          hint={t("heldHint")}
        />
        <StatCard
          label={t("reserved")}
          value={money(balance.data?.reserved, balance.data?.currency)}
        />
      </section>

      <section className="grid-ruled grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4">
        {PERIODS.map(({ period, key }) => {
          const q = byPeriod[period];
          // The labels say "за 30 дней", not "за месяц", because the API
          // computes rolling windows. Wording that implied a calendar month
          // would be wrong every day except the last one.
          return (
            <div key={period} className="bg-bg px-5 py-6 sm:px-6">
              <span className="text-tx-mute block font-mono text-[11px] uppercase tracking-[0.12em]">
                {t(key)}
              </span>
              <p className="font-display text-primary mt-3 break-words text-[22px] font-extrabold leading-none tracking-[-0.03em]">
                {money(q.data?.earned)}
              </p>
              <dl className="text-tx-dim mt-4 space-y-1.5 text-[12px]">
                <div className="flex justify-between gap-2">
                  <dt>{t("orders")}</dt>
                  <dd className="font-mono">{q.data?.orders ?? 0}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt>{t("activations")}</dt>
                  <dd className="font-mono">{q.data?.activations ?? 0}</dd>
                </div>
              </dl>
            </div>
          );
        })}
      </section>
    </div>
  );
}
