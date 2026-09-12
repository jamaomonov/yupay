/** Pure helpers for the admin post form. No network. */

import type { AdminPost, Locale } from "./types";

export const PIN_CAP = 2;

export interface FaqDraft {
  locale: Locale;
  sort_order: number;
  question: string;
  answer: string;
}

export type EventPhase = "missing" | "invalid" | "upcoming" | "live" | "ended";

export function packFaqs(rows: readonly FaqDraft[]): FaqDraft[] | "incomplete" {
  const kept: FaqDraft[] = [];
  for (const row of rows) {
    const question = row.question.trim();
    const answer = row.answer.trim();
    if (!question && !answer) continue;
    if (!question || !answer) return "incomplete";
    kept.push({ locale: row.locale, sort_order: row.sort_order, question, answer });
  }
  const byLocale = new Map<Locale, number>();
  return kept.map((row) => {
    const next = byLocale.get(row.locale) ?? 0;
    byLocale.set(row.locale, next + 1);
    return { ...row, sort_order: next };
  });
}

export function eventPhase(start: string, end: string, nowMs = Date.now()): EventPhase {
  if (!start || !end) return "missing";
  const starts = Date.parse(start);
  const ends = Date.parse(end);
  if (Number.isNaN(starts) || Number.isNaN(ends) || ends <= starts) return "invalid";
  if (nowMs < starts) return "upcoming";
  if (nowMs > ends) return "ended";
  return "live";
}

export function toDatetimeLocal(iso: string): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number): string => String(n).padStart(2, "0");
  return `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function fromDatetimeLocal(local: string): string {
  if (!local) return "";
  const date = new Date(local);
  return Number.isNaN(date.getTime()) ? "" : date.toISOString();
}

export function otherPublishedPins(
  items: readonly Pick<AdminPost, "id" | "primary_brand_id" | "pin_on_brand" | "status">[],
  brandId: string,
  excludingId: string | undefined,
): number {
  return items.filter(
    (post) =>
      post.primary_brand_id === brandId &&
      post.pin_on_brand &&
      post.status === "published" &&
      post.id !== excludingId,
  ).length;
}
