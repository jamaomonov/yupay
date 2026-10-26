"use client";

import type { LucideIcon } from "lucide-react";

import { BrandMark } from "@/components/BrandMark";
import { dollars, toCents } from "@/lib/money";

export interface TopRow {
  key: string;
  title: string;
  subtitle?: string;
  brandName: string | null;
  logoUrl: string | null;
  orders: string;
  spendUsd: string;
}

interface TopListProps {
  icon: LucideIcon;
  title: string;
  empty: string;
  rows: TopRow[];
}

/**
 * A ranked list with a share bar under each row. The bar is the row's spend
 * against the leader's, not against the total: it compares rows, and the
 * leader always reads as full.
 */
export function TopList({ icon: Icon, title, empty, rows }: TopListProps) {
  const lead = rows.reduce((best, row) => {
    const cents = toCents(row.spendUsd);
    return cents > best ? cents : best;
  }, 0n);

  return (
    <section className="border-border bg-card min-w-0 rounded-xl border p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold">
        <Icon aria-hidden size={15} className="text-tx-dim shrink-0" />
        {title}
      </h2>
      {rows.length === 0 ? (
        <p className="text-tx-dim mt-4 text-sm">{empty}</p>
      ) : (
        <ol className="mt-3 space-y-3">
          {rows.map((row, index) => {
            const cents = toCents(row.spendUsd);
            const share = lead === 0n ? 0 : Number((cents * 1000n) / lead) / 10;
            return (
              <li key={row.key} className="flex items-start gap-3">
                <span className="text-tx-dim w-4 shrink-0 pt-1.5 text-right font-mono text-xs">
                  {index + 1}
                </span>
                <BrandMark name={row.brandName} logoUrl={row.logoUrl} size="sm" />
                <div className="min-w-0 flex-1">
                  <div className="flex items-baseline justify-between gap-3 text-sm">
                    <span className="min-w-0 truncate font-medium">{row.title}</span>
                    <span className="shrink-0 font-mono text-xs font-semibold">
                      {dollars(cents)}
                    </span>
                  </div>
                  <div className="text-tx-dim mt-0.5 flex justify-between gap-3 text-xs">
                    <span className="min-w-0 truncate">{row.subtitle ?? ""}</span>
                    <span className="shrink-0">{row.orders}</span>
                  </div>
                  <div className="bg-card-2 mt-1.5 h-1 overflow-hidden rounded-full">
                    <div
                      className="bg-primary/60 h-full rounded-full"
                      style={{ width: `${String(share)}%` }}
                    />
                  </div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
