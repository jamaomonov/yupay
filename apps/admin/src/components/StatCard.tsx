/**
 * The KPI tile used above every list page.
 *
 * It existed five times — orders, SKUs, audit, FX, webhooks — with the same
 * markup and five different prop sets, so a change to the card meant finding
 * all five. This is their union.
 */

import type { ReactNode } from "react";

export interface StatCardProps {
  label: ReactNode;
  /**
   * The figure. A node rather than a number so a tile can hold a sparkline or
   * a composed value (the audit page needs both).
   */
  value: ReactNode;
  /** Paints the figure with the accent colour — for the headline tile of a row. */
  accent?: boolean;
  /**
   * `warn` marks a figure that wants attention; `muted` dims one that is
   * currently uninteresting — typically a counter sitting at zero.
   */
  tone?: "default" | "warn" | "muted";
  /** Tabular figures, for rates and ids. */
  mono?: boolean;
  className?: string;
}

export function StatCard({
  label,
  value,
  accent,
  tone = "default",
  mono,
  className = "",
}: StatCardProps) {
  // `accent` wins over `tone`: a headline tile stays the headline even when
  // the number it holds happens to be zero.
  const valueCls = accent
    ? "text-[var(--accent)]"
    : tone === "warn"
      ? "text-[var(--danger)]"
      : // Previously "muted" rendered identically to "default" in all five
        // copies, so a zeroed counter looked exactly as loud as a live one.
        tone === "muted"
        ? "text-[var(--text-secondary)]"
        : "text-[var(--text-primary)]";

  return (
    <div
      className={`rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)] ${className}`}
    >
      <div className={`text-2xl font-semibold ${valueCls} ${mono ? "font-mono" : ""}`}>{value}</div>
      <div className="mt-1 text-xs uppercase tracking-wide text-[var(--text-secondary)]">
        {label}
      </div>
    </div>
  );
}
