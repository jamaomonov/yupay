/**
 * The Statistics screen's arithmetic: which window a period names, how a bar is
 * labelled, and how much a number moved against the window before.
 *
 * The browser decides the window, as it does for the dashboard's «today»: it
 * knows when its own day started, and the bars must agree with the dates on the
 * Orders list.
 */

import { toCents } from "@/lib/money";

export type Preset = "24h" | "7d" | "30d" | "all";

export const PRESETS: readonly Preset[] = ["24h", "7d", "30d", "all"];

export interface Window {
  /** `null` for all time. */
  since: Date | null;
  /** `null` for now. */
  until: Date | null;
}

const HOUR = 3_600_000;
const DAY = 24 * HOUR;

/** A preset as a window ending now. `now` is for tests. */
export function presetWindow(preset: Preset, now: Date = new Date()): Window {
  switch (preset) {
    case "24h":
      return { since: new Date(now.getTime() - DAY), until: null };
    case "7d":
      return { since: new Date(now.getTime() - 7 * DAY), until: null };
    case "30d":
      return { since: new Date(now.getTime() - 30 * DAY), until: null };
    case "all":
      return { since: null, until: null };
    default:
      return assertNever(preset);
  }
}

/**
 * Two `<input type="date">` values as a window of whole local days: from the
 * first day's midnight to the midnight after the last. `null` when either is
 * empty or the range is inverted.
 */
export function rangeWindow(from: string, to: string): Window | null {
  const start = localMidnight(from);
  const last = localMidnight(to);
  if (start === null || last === null || last < start) return null;
  const until = new Date(last);
  until.setDate(until.getDate() + 1);
  return { since: start, until };
}

function localMidnight(value: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (match === null) return null;
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

/** The `/stats` query for a window, with the browser's own zone. */
export function statsQuery(window: Window, tz: string): string {
  const params = new URLSearchParams({ tz });
  if (window.since !== null) params.set("since", window.since.toISOString());
  if (window.until !== null) params.set("until", window.until.toISOString());
  return `/stats?${params.toString()}`;
}

/** `YYYY-MM-DD` for a date input, on the local clock. */
export function dateInputValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/**
 * Percent change against the window before, rounded. `null` when there is
 * nothing to compare with — a rise «from zero» is not a percentage.
 */
export function change(current: number, previous: number | null | undefined): number | null {
  if (previous === null || previous === undefined || previous === 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}

/** `change` for two decimal-dollar strings, compared in cents. */
export function moneyChange(current: string, previous: string | null | undefined): number | null {
  if (previous === null || previous === undefined) return null;
  return change(Number(toCents(current)), Number(toCents(previous)));
}

/** A bar's label: «14:00», «18 окт.», «окт. 2026». */
export function bucketLabel(
  iso: string,
  granularity: "hour" | "day" | "month",
  locale: string,
): string {
  const date = new Date(iso);
  switch (granularity) {
    case "hour":
      return new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit" }).format(date);
    case "day":
      return new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" }).format(date);
    case "month":
      return new Intl.DateTimeFormat(locale, { month: "short", year: "numeric" }).format(date);
    default:
      return assertNever(granularity);
  }
}

/** Delivered as a share of everything that finished; `null` while nothing has. */
export function successShare(delivered: number, failed: number): number | null {
  const finished = delivered + failed;
  return finished === 0 ? null : Math.round((delivered / finished) * 100);
}

function assertNever(value: never): never {
  throw new Error(`unexpected value: ${String(value)}`);
}
