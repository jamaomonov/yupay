import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import { usd } from "./format";

import type { AnalyticsChannel, BusinessAnalytics, RevenuePoint } from "./types";

import { Spinner } from "@/components/States";
import { apiGet } from "@/lib/api";

const MONTHS = [
  "Январь",
  "Февраль",
  "Март",
  "Апрель",
  "Май",
  "Июнь",
  "Июль",
  "Август",
  "Сентябрь",
  "Октябрь",
  "Ноябрь",
  "Декабрь",
];
/** Monday first — a Russian week, and the one an operator reads. */
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

/** Local midnight, formatted as the API's `since`/`until` expect. */
function isoAt(year: number, month: number, day: number): string {
  return new Date(year, month, day).toISOString();
}

/** `YYYY-MM-DD` in local time — the key the series is indexed by. */
function localKey(year: number, month: number, day: number): string {
  const d = new Date(year, month, day);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * A month of days, each showing what it earned and what it kept.
 *
 * The question this answers is the one a table of thirty rows does not: which
 * days were good. Revenue alone cannot say — a day can take $400 and keep $12
 * — so the cell carries both, and the tint is keyed on **margin**, because
 * that is the number being compared.
 */
export function CalendarTab({
  channel,
  onPick,
}: {
  /** Retail, B2B or both — the grid is painted for the same half of the
   *  business the tab above it is showing. */
  channel: AnalyticsChannel;
  /** Opens the detail view for a day or a span. `until` is exclusive. */
  onPick: (since: string, until: string, label: string) => void;
}) {
  const today = new Date();
  const [cursor, setCursor] = useState({ y: today.getFullYear(), m: today.getMonth() });
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const since = isoAt(cursor.y, cursor.m, 1);
  const until = isoAt(cursor.y, cursor.m + 1, 1);
  const monthQuery = useQuery<BusinessAnalytics>({
    queryKey: ["admin", "stats", "analytics", "calendar", since, until, channel],
    queryFn: () =>
      apiGet<BusinessAnalytics>(
        `/api/v1/admin/stats/analytics/business?since=${encodeURIComponent(since)}&until=${encodeURIComponent(until)}&channel=${channel}`,
      ),
  });

  const byDay = useMemo(() => {
    const map = new Map<string, RevenuePoint>();
    for (const point of monthQuery.data?.revenue_series ?? []) map.set(point.date, point);
    return map;
  }, [monthQuery.data]);

  // The tint is relative to the best day in the month on screen, not to some
  // absolute scale: a quiet month should still show its shape.
  const peakMargin = useMemo(() => {
    let peak = 0;
    for (const point of byDay.values()) peak = Math.max(peak, Number(point.margin_usd ?? 0));
    return peak;
  }, [byDay]);

  const first = new Date(cursor.y, cursor.m, 1);
  // `getDay()` is Sunday-first; shift so Monday is column one.
  const lead = (first.getDay() + 6) % 7;
  const daysInMonth = new Date(cursor.y, cursor.m + 1, 0).getDate();
  const monthLabel = `${MONTHS[cursor.m] ?? ""} ${String(cursor.y)}`;

  const step = (by: number) => {
    setCursor((c) => {
      const d = new Date(c.y, c.m + by, 1);
      return { y: d.getFullYear(), m: d.getMonth() };
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            aria-label="Предыдущий месяц"
            onClick={() => {
              step(-1);
            }}
            className="rounded-md border border-[var(--border-default)] p-1.5 text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            <ChevronLeft className="size-4" aria-hidden="true" />
          </button>
          <span className="min-w-[10rem] text-center text-sm font-semibold">{monthLabel}</span>
          <button
            type="button"
            aria-label="Следующий месяц"
            onClick={() => {
              step(1);
            }}
            className="rounded-md border border-[var(--border-default)] p-1.5 text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            <ChevronRight className="size-4" aria-hidden="true" />
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {/* An arbitrary span, beside the month. Two dates rather than a
              range widget: the operator already knows the two days they mean,
              and a picker that has to be learned is slower than typing them. */}
          <input
            type="date"
            aria-label="Период с"
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
            }}
            className="rounded-md border border-[var(--border-default)] bg-transparent px-2 py-1.5 text-sm"
          />
          <span className="text-sm text-[var(--text-secondary)]">по</span>
          <input
            type="date"
            aria-label="Период по"
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
            }}
            className="rounded-md border border-[var(--border-default)] bg-transparent px-2 py-1.5 text-sm"
          />
          <button
            type="button"
            disabled={from === "" || to === "" || to < from}
            onClick={() => {
              // `until` is exclusive, so the chosen end date has to be
              // included by asking for the morning after it.
              const end = new Date(`${to}T00:00:00`);
              end.setDate(end.getDate() + 1);
              onPick(
                new Date(`${from}T00:00:00`).toISOString(),
                end.toISOString(),
                `${from} — ${to}`,
              );
            }}
            className="rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-45"
          >
            Разбор за период
          </button>
          <button
            type="button"
            onClick={() => {
              onPick(since, until, monthLabel);
            }}
            className="rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            Разбор за месяц
          </button>
        </div>
      </div>

      {monthQuery.isLoading ? (
        <Spinner label="Считаем…" />
      ) : (
        <div>
          <div className="mb-1 grid grid-cols-7 gap-1.5">
            {WEEKDAYS.map((w) => (
              <div key={w} className="text-center text-[11px] text-[var(--text-secondary)]">
                {w}
              </div>
            ))}
          </div>
          <div className="grid grid-cols-7 gap-1.5">
            {Array.from({ length: lead }, (_, i) => (
              <div key={`lead-${String(i)}`} aria-hidden="true" />
            ))}
            {Array.from({ length: daysInMonth }, (_, i) => {
              const day = i + 1;
              const point = byDay.get(localKey(cursor.y, cursor.m, day));
              const margin = Number(point?.margin_usd ?? 0);
              // Floor at 8% so a day with any margin at all is still visibly
              // not an empty one.
              const tint = peakMargin > 0 && margin > 0 ? Math.max(0.08, margin / peakMargin) : 0;
              const dayIso = isoAt(cursor.y, cursor.m, day);
              const nextIso = isoAt(cursor.y, cursor.m, day + 1);
              const label = `${String(day)} ${MONTHS[cursor.m] ?? ""}`;
              return (
                <button
                  key={day}
                  type="button"
                  disabled={point === undefined}
                  onClick={() => {
                    onPick(dayIso, nextIso, label);
                  }}
                  title={point === undefined ? "Нет оплаченных заказов" : label}
                  className="min-h-[76px] rounded-lg border border-[var(--border-default)] p-2 text-left transition enabled:hover:border-[var(--accent)] disabled:opacity-45"
                  style={
                    tint > 0
                      ? {
                          backgroundColor: `color-mix(in srgb, var(--accent) ${String(Math.round(tint * 28))}%, transparent)`,
                        }
                      : undefined
                  }
                >
                  <div className="text-[11px] text-[var(--text-secondary)]">{day}</div>
                  {point !== undefined && (
                    <>
                      <div className="mt-1 text-[13px] font-semibold tabular-nums">
                        {usd(point.revenue_usd)}
                      </div>
                      <div className="text-[11px] tabular-nums text-[var(--text-secondary)]">
                        {point.margin_usd === null ? "маржа —" : `+${usd(point.margin_usd)}`}
                      </div>
                    </>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
