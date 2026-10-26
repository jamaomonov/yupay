"use client";

import { BarChart3, Layers, Trophy } from "lucide-react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";

import type { Stats } from "@/lib/types";

import { EmptyState } from "@/components/EmptyState";
import { ListSkeleton } from "@/components/ListSkeleton";
import { LoadError } from "@/components/LoadError";
import { PageHeading } from "@/components/PageHeading";
import { StatsChart } from "@/components/stats/StatsChart";
import { TopList } from "@/components/stats/TopList";
import { api } from "@/lib/api";
import { dollars, toCents } from "@/lib/money";
import {
  PRESETS,
  type Preset,
  type Window,
  change,
  dateInputValue,
  moneyChange,
  presetWindow,
  rangeWindow,
  statsQuery,
  successShare,
} from "@/lib/stats";

type Period = Preset | "range";

/**
 * Statistics: how many orders, for how much, and on what — over a preset or a
 * date range. Every number is computed by `GET /stats` from the ledger; the
 * page only picks the window and draws.
 */
export default function StatsPage() {
  const t = useTranslations("merchant.stats");
  const { locale } = useParams<{ locale: string }>();
  const [period, setPeriod] = useState<Period>("7d");
  const [from, setFrom] = useState(() => dateInputValue(new Date(Date.now() - 6 * 86_400_000)));
  const [to, setTo] = useState(() => dateInputValue(new Date()));
  const [stats, setStats] = useState<Stats | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback((window: Window) => {
    setFailed(false);
    setStats(null);
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    void api<Stats>(statsQuery(window, tz))
      .then(setStats)
      .catch(() => {
        setFailed(true);
      });
  }, []);

  const range = rangeWindow(from, to);
  const current = period === "range" ? range : presetWindow(period);

  useEffect(() => {
    if (period !== "range") load(presetWindow(period));
  }, [period, load]);

  const retry = () => {
    if (current !== null) load(current);
  };

  return (
    <div>
      <PageHeading icon={BarChart3} title={t("title")} />

      <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label={t("periodLabel")}>
        {[...PRESETS, "range" as const].map((p) => (
          <button
            key={p}
            type="button"
            aria-pressed={period === p}
            onClick={() => {
              setPeriod(p);
            }}
            className={`rounded-btn border px-3.5 py-2 text-sm font-semibold ${
              period === p
                ? "border-primary bg-primary/10 text-primary-ink"
                : "border-border text-tx-mute"
            }`}
          >
            {t(`period_${p}`)}
          </button>
        ))}
      </div>

      {period === "range" && (
        <form
          className="mt-3 flex flex-wrap items-end gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (range !== null) load(range);
          }}
        >
          <label className="text-tx-dim flex flex-col gap-1 text-xs">
            {t("from")}
            <input
              type="date"
              value={from}
              max={to}
              onChange={(event) => {
                setFrom(event.target.value);
              }}
              className="border-border bg-card rounded-btn text-foreground border px-3 py-2 text-sm"
            />
          </label>
          <label className="text-tx-dim flex flex-col gap-1 text-xs">
            {t("to")}
            <input
              type="date"
              value={to}
              min={from}
              max={dateInputValue(new Date())}
              onChange={(event) => {
                setTo(event.target.value);
              }}
              className="border-border bg-card rounded-btn text-foreground border px-3 py-2 text-sm"
            />
          </label>
          <button
            type="submit"
            disabled={range === null}
            className="bg-primary text-primary-foreground rounded-btn px-4 py-2 text-sm font-semibold disabled:opacity-50"
          >
            {t("show")}
          </button>
        </form>
      )}

      {failed && <LoadError onRetry={retry} />}
      {!failed && stats === null && period !== "range" && (
        <ListSkeleton rows={4} className="mt-5" />
      )}
      {stats !== null && <StatsBody stats={stats} locale={locale} />}
    </div>
  );
}

function StatsBody({ stats, locale }: { stats: Stats; locale: string }) {
  const t = useTranslations("merchant.stats");
  const { totals, previous } = stats;

  if (totals.orders === 0) {
    return (
      <div className="mt-5">
        <EmptyState icon={BarChart3} title={t("empty")} />
      </div>
    );
  }

  const share = successShare(totals.delivered, totals.failed);
  const prevShare = previous ? successShare(previous.delivered, previous.failed) : null;

  return (
    <div className="mt-5 space-y-4">
      <dl className="grid grid-cols-2 gap-2.5 sm:gap-3.5 lg:grid-cols-4">
        <Kpi
          label={t("kpiSpend")}
          value={dollars(toCents(totals.spend_usd))}
          delta={moneyChange(totals.spend_usd, previous?.spend_usd)}
          accent
        />
        <Kpi
          label={t("kpiOrders")}
          value={String(totals.orders)}
          delta={change(totals.orders, previous?.orders)}
        />
        <Kpi
          label={t("kpiAverage")}
          value={dollars(toCents(totals.avg_order_usd))}
          delta={moneyChange(totals.avg_order_usd, previous?.avg_order_usd)}
        />
        <Kpi
          label={t("kpiSuccess")}
          value={share === null ? "—" : `${String(share)}%`}
          delta={share === null || prevShare === null ? null : share - prevShare}
          points
        />
      </dl>

      <ul className="text-tx-mute flex flex-wrap gap-x-5 gap-y-1 text-xs">
        <li>{t("lineDelivered", { count: totals.delivered })}</li>
        <li>{t("lineFailed", { count: totals.failed })}</li>
        {totals.in_flight > 0 && <li>{t("lineInFlight", { count: totals.in_flight })}</li>}
        {toCents(totals.refunded_usd) > 0n && (
          <li>{t("lineRefunded", { amount: dollars(toCents(totals.refunded_usd)) })}</li>
        )}
        <li>{t("lineChannels", { api: stats.api_orders, cabinet: stats.cabinet_orders })}</li>
      </ul>

      <StatsChart series={stats.series} granularity={stats.granularity} locale={locale} />

      <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
        <TopList
          icon={Trophy}
          title={t("topBrands")}
          empty={t("empty")}
          rows={stats.brands.map((b, i) => ({
            key: `${b.brand_name ?? ""}-${String(i)}`,
            title: b.brand_name ?? "—",
            brandName: b.brand_name,
            logoUrl: b.logo_url,
            orders: t("ordersCount", { count: b.orders }),
            spendUsd: b.spend_usd,
          }))}
        />
        <TopList
          icon={Layers}
          title={t("topSkus")}
          empty={t("empty")}
          rows={stats.skus.map((s) => ({
            key: s.sku_code,
            title: s.sku_name ?? s.sku_code,
            subtitle: s.brand_name ?? "",
            brandName: s.brand_name,
            logoUrl: s.logo_url,
            orders: t("ordersCount", { count: s.orders }),
            spendUsd: s.spend_usd,
          }))}
        />
      </div>
    </div>
  );
}

/**
 * A number with its movement against the window before. `points` says the
 * delta is in percentage points (a rate's change), not a percent of itself.
 */
function Kpi({
  label,
  value,
  delta,
  accent,
  points,
}: {
  label: string;
  value: string;
  delta: number | null;
  accent?: boolean;
  points?: boolean;
}) {
  const t = useTranslations("merchant.stats");
  return (
    <div className="border-border bg-card flex flex-col-reverse rounded-xl border px-4 py-4 sm:px-5">
      <dt className="text-tx-dim mt-1 text-xs sm:text-[12.5px]">{label}</dt>
      <dd>
        <span
          className={`font-mono text-xl font-extrabold sm:text-2xl ${accent ? "text-primary-ink" : ""}`}
        >
          {value}
        </span>
        {delta !== null && (
          <span
            title={t("vsBefore")}
            className={`ml-2 align-middle text-xs font-semibold ${
              delta > 0 ? "text-primary-ink" : delta < 0 ? "text-danger" : "text-tx-dim"
            }`}
          >
            {delta > 0 ? "↑" : delta < 0 ? "↓" : ""}
            {Math.abs(delta)}
            {points ? t("pp") : "%"}
          </span>
        )}
      </dd>
    </div>
  );
}
