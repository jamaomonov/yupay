import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

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
/** For "10 сентября" — a date reads in the genitive, a month heading does not. */
const MONTHS_OF = [
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
];
/** Monday first — a Russian week, and the one an operator reads. */
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

const DAY_MS = 86_400_000;

/** Local midnight, formatted as the API's `since`/`until` expect.
 *
 *  "Local" is the *browser's* clock, and the server buckets its day series on
 *  Asia/Tashkent (`_local_day` in `stats/analytics/business.py`). The two agree
 *  for an operator sitting in Uzbekistan, which is every operator today, and
 *  disagree by the offset for one who is not — the cell would again be a
 *  different 24 hours from the window its click opens. If the admin ever has a
 *  user outside UZ, this is the line that has to build Tashkent midnight
 *  explicitly rather than trusting the host clock. */
function isoAt(year: number, month: number, day: number): string {
  return new Date(year, month, day).toISOString();
}

/** `YYYY-MM-DD` in local time — the key the series is indexed by. */
function localKey(year: number, month: number, day: number): string {
  const d = new Date(year, month, day);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${String(d.getFullYear())}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** "10 сентября" — what an operator would say out loud. */
function dayLabel(d: Date): string {
  return `${String(d.getDate())} ${MONTHS_OF[d.getMonth()] ?? ""}`;
}

/**
 * A month of days, each showing what it earned and what it kept.
 *
 * The question this answers is the one a table of thirty rows does not: which
 * days were good. Revenue alone cannot say — a day can take $400 and keep $12
 * — so the cell carries both, and the tint is keyed on **margin**, because
 * that is the number being compared.
 *
 * A period is picked by clicking its two ends on the grid. It used to be two
 * `дд.мм.гггг` boxes, which asked an operator to type a month and a year to
 * ask about last Tuesday; the anchor survives the month stepper, so a span
 * across a month boundary is still two clicks.
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
  // The first end of a pending span. Deliberately not cleared when the month
  // steps, so "с 28 августа по 3 сентября" is the same two clicks as any
  // other span.
  const [anchor, setAnchor] = useState<Date | null>(null);
  const [hovered, setHovered] = useState<Date | null>(null);

  const since = isoAt(cursor.y, cursor.m, 1);
  const until = isoAt(cursor.y, cursor.m + 1, 1);
  const monthQuery = useQuery<BusinessAnalytics>({
    queryKey: ["admin", "stats", "analytics", "calendar", since, until, channel],
    queryFn: () =>
      apiGet<BusinessAnalytics>(
        `/api/v1/admin/stats/analytics/business?since=${encodeURIComponent(since)}&until=${encodeURIComponent(until)}&channel=${channel}`,
      ),
  });

  // Escape abandons a half-made selection. Without it the only way out of the
  // pending state is to complete a span you no longer want.
  useEffect(() => {
    if (anchor === null) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setAnchor(null);
        setHovered(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [anchor]);

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

  /** The span currently being previewed: the anchor plus whatever the pointer
   *  is over, in whichever order they were clicked. */
  const preview = useMemo(() => {
    if (anchor === null) return null;
    const other = hovered ?? anchor;
    const a = Math.min(anchor.getTime(), other.getTime());
    const b = Math.max(anchor.getTime(), other.getTime());
    return { from: a, to: b };
  }, [anchor, hovered]);

  const choose = (day: Date) => {
    if (anchor === null) {
      setAnchor(day);
      return;
    }
    const from = new Date(Math.min(anchor.getTime(), day.getTime()));
    const to = new Date(Math.max(anchor.getTime(), day.getTime()));
    // `until` is exclusive, so the chosen end day has to be included by
    // asking for the morning after it. Clicking the same day twice is one day.
    const end = new Date(to.getTime() + DAY_MS);
    const label =
      from.getTime() === to.getTime() ? dayLabel(from) : `${dayLabel(from)} — ${dayLabel(to)}`;
    setAnchor(null);
    setHovered(null);
    onPick(from.toISOString(), end.toISOString(), label);
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

      {/* The instruction lives on screen only while it is actionable. A
          permanent "кликните два дня" is read once and then becomes furniture. */}
      <div role="status" className="text-xs text-[var(--text-secondary)]" aria-live="polite">
        {anchor === null ? (
          "Кликните день — или два дня, чтобы разобрать период между ними."
        ) : (
          <span className="inline-flex items-center gap-2">
            Начало: <strong className="font-semibold">{dayLabel(anchor)}</strong> · выберите второй
            день (тот же — за один день)
            <button
              type="button"
              onClick={() => {
                setAnchor(null);
                setHovered(null);
              }}
              className="inline-flex items-center gap-1 rounded border border-[var(--border-default)] px-1.5 py-0.5 hover:text-[var(--text-primary)]"
            >
              <X className="size-3" aria-hidden="true" />
              Отмена
            </button>
          </span>
        )}
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
          <div
            className="grid grid-cols-7 gap-1.5"
            onMouseLeave={() => {
              setHovered(null);
            }}
          >
            {Array.from({ length: lead }, (_, i) => (
              <div key={`lead-${String(i)}`} aria-hidden="true" />
            ))}
            {Array.from({ length: daysInMonth }, (_, i) => {
              const day = i + 1;
              const date = new Date(cursor.y, cursor.m, day);
              const point = byDay.get(localKey(cursor.y, cursor.m, day));
              const margin = Number(point?.margin_usd ?? 0);
              // Floor at 8% so a day with any margin at all is still visibly
              // not an empty one.
              const tint = peakMargin > 0 && margin > 0 ? Math.max(0.08, margin / peakMargin) : 0;
              const inPreview =
                preview !== null && date.getTime() >= preview.from && date.getTime() <= preview.to;
              const isAnchor = anchor !== null && anchor.getTime() === date.getTime();
              return (
                <button
                  key={day}
                  type="button"
                  onMouseEnter={() => {
                    setHovered(date);
                  }}
                  onFocus={() => {
                    setHovered(date);
                  }}
                  onClick={() => {
                    choose(date);
                  }}
                  // Days with nothing sold stay selectable: "с 10 по 14" is a
                  // perfectly ordinary question when the 10th was quiet, and
                  // an unclickable end makes it unaskable.
                  aria-label={
                    point === undefined
                      ? `${dayLabel(date)} — нет оплаченных заказов`
                      : `${dayLabel(date)} — выручка ${usd(point.revenue_usd)}${point.margin_usd === null ? "" : `, маржа ${usd(point.margin_usd)}`}`
                  }
                  className={`min-h-[76px] rounded-lg border p-2 text-left transition hover:border-[var(--accent)] ${
                    isAnchor
                      ? "border-[var(--accent)] ring-2 ring-[var(--accent)]"
                      : inPreview
                        ? "border-[var(--accent)]"
                        : "border-[var(--border-default)]"
                  } ${point === undefined ? "opacity-45" : ""}`}
                  style={
                    tint > 0 || inPreview
                      ? {
                          backgroundColor: inPreview
                            ? "var(--bg-accent-soft)"
                            : `color-mix(in srgb, var(--accent) ${String(Math.round(tint * 28))}%, transparent)`,
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
