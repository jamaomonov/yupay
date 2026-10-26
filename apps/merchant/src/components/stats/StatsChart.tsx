"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import type { StatsPoint } from "@/lib/types";

import { dollars, toCents } from "@/lib/money";
import { bucketLabel } from "@/lib/stats";

type Metric = "spend" | "orders";

interface StatsChartProps {
  series: StatsPoint[];
  granularity: "hour" | "day" | "month";
  locale: string;
}

/**
 * Bars over time, spend or order count. Plain divs, no chart library: the
 * cabinet's bundle has none and a bar per bucket needs none. A tap or hover
 * picks a bar and the line above it says what it holds — a phone has no
 * hover, so the reading cannot live in a tooltip alone.
 */
export function StatsChart({ series, granularity, locale }: StatsChartProps) {
  const t = useTranslations("merchant.stats");
  const [metric, setMetric] = useState<Metric>("spend");
  const [picked, setPicked] = useState<number | null>(null);

  const values = series.map((p) => (metric === "spend" ? Number(toCents(p.spend_usd)) : p.orders));
  const max = Math.max(1, ...values);
  const shown = picked === null ? null : series[picked];
  const middle = series[Math.floor(series.length / 2)];
  const first = series[0];
  const last = series[series.length - 1];

  return (
    <section className="border-border bg-card min-w-0 rounded-xl border p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold">{t("chartTitle")}</h2>
        <div role="group" className="bg-card-2 rounded-btn inline-flex p-0.5 text-xs">
          {(["spend", "orders"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={metric === m}
              onClick={() => {
                setMetric(m);
              }}
              className={`rounded-btn px-3 py-1.5 font-semibold ${
                metric === m ? "bg-card text-foreground shadow-sm" : "text-tx-mute"
              }`}
            >
              {t(m === "spend" ? "metricSpend" : "metricOrders")}
            </button>
          ))}
        </div>
      </div>

      <p className="text-tx-mute mt-2 min-h-5 text-xs" aria-live="polite">
        {shown === undefined || shown === null
          ? t("chartHint")
          : `${bucketLabel(shown.at, granularity, locale)} · ${t("ordersCount", {
              count: shown.orders,
            })} · ${dollars(toCents(shown.spend_usd))}`}
      </p>

      <div
        className="mt-3 flex h-40 items-end gap-px sm:gap-0.5"
        onMouseLeave={() => {
          setPicked(null);
        }}
      >
        {series.map((point, index) => {
          const value = values[index] ?? 0;
          return (
            <button
              key={point.at}
              type="button"
              aria-label={`${bucketLabel(point.at, granularity, locale)}: ${t("ordersCount", {
                count: point.orders,
              })}, ${dollars(toCents(point.spend_usd))}`}
              onMouseEnter={() => {
                setPicked(index);
              }}
              onFocus={() => {
                setPicked(index);
              }}
              onClick={() => {
                setPicked(index);
              }}
              className="group flex h-full min-w-0 flex-1 items-end"
            >
              <span
                className={`block w-full rounded-t-sm transition-colors ${
                  picked === index ? "bg-primary" : "bg-primary/45 group-hover:bg-primary/70"
                }`}
                // Zero stays visible as a hairline, so an empty day reads as
                // «nothing» rather than as a gap in the data.
                style={{
                  height: value === 0 ? "2px" : `${String(Math.max(3, (value / max) * 100))}%`,
                }}
              />
            </button>
          );
        })}
      </div>

      {first !== undefined && last !== undefined && (
        <div className="text-tx-dim mt-2 flex justify-between gap-2 text-[11px]">
          <span>{bucketLabel(first.at, granularity, locale)}</span>
          {middle !== undefined && series.length > 4 && (
            <span>{bucketLabel(middle.at, granularity, locale)}</span>
          )}
          <span>{bucketLabel(last.at, granularity, locale)}</span>
        </div>
      )}
    </section>
  );
}
