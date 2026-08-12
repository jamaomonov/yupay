/** Full supplier-cost history for one SKU, opened from {@link SkuPriceHistoryCard}.
 *
 * The card only ever fetches 30 points (enough for the sparkline + a quick
 * glance); this fetches the server's actual ceiling of 500 so "смотреть всю
 * историю" isn't a lie. Each row spells out было → стало explicitly rather
 * than making the operator do the subtraction from a bare percentage. */

import { useQuery } from "@tanstack/react-query";
import { TrendingDown, TrendingUp, X } from "lucide-react";
import { useRef } from "react";

import type { PriceHistoryListOut, PricePoint } from "./types";

import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useDialog } from "@/lib/useDialog";

const FULL_HISTORY_LIMIT = 500;
const FULL_HISTORY_LIMIT_STR = String(FULL_HISTORY_LIMIT);

interface Props {
  skuId: string;
  skuCode: string;
  onClose: () => void;
}

export function SkuPriceHistoryModal({ skuId, skuCode, onClose }: Props) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  useDialog({ open: true, onClose, containerRef: dialogRef });

  const query = useQuery<PriceHistoryListOut>({
    queryKey: qk.skuPriceHistoryFull(skuId),
    queryFn: () =>
      apiGet<PriceHistoryListOut>(
        `/api/v1/admin/integrations/sku-prices/${skuId}/history?limit=${FULL_HISTORY_LIMIT_STR}`,
      ),
    staleTime: 60_000,
  });

  const items = query.data?.items ?? [];

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="price-history-title"
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 px-4 pt-[8vh] backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[84vh] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-md)]">
        <header className="flex items-center justify-between border-b border-[var(--border-subtle)] px-5 py-3">
          <div>
            <h2 id="price-history-title" className="text-sm font-semibold">
              История цены поставщика
            </h2>
            <p className="text-xs text-[var(--text-tertiary)]">{skuCode}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)]"
            aria-label="Закрыть"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="overflow-y-auto">
          {query.isLoading ? (
            <p className="px-5 py-6 text-xs text-[var(--text-tertiary)]">Загрузка…</p>
          ) : items.length === 0 ? (
            <p className="px-5 py-6 text-xs text-[var(--text-tertiary)]">Истории пока нет.</p>
          ) : (
            <>
              <div className="grid grid-cols-[auto_1fr_auto] gap-3 border-b border-[var(--border-subtle)] px-5 py-2 text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
                <span>Дата</span>
                <span>Было → стало</span>
                <span className="text-right">Изменение</span>
              </div>
              <ul className="divide-y divide-[var(--border-subtle)]">
                {items.map((p) => (
                  <DetailRow key={p.id} point={p} />
                ))}
              </ul>
              {items.length >= FULL_HISTORY_LIMIT && (
                <p className="px-5 py-3 text-[10px] text-[var(--text-tertiary)]">
                  Показаны последние {FULL_HISTORY_LIMIT} точек — более ранние записи не загружены.
                </p>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function DetailRow({ point }: { point: PricePoint }) {
  const prev = point.previous_cost_usdt ? Number.parseFloat(point.previous_cost_usdt) : null;
  const curr = Number.parseFloat(point.cost_usdt);
  const delta = prev !== null && prev !== 0 ? ((curr - prev) / prev) * 100 : null;
  const trendUp = delta !== null && delta > 0;
  const trendDown = delta !== null && delta < 0;

  return (
    <li className="grid grid-cols-[auto_1fr_auto] items-center gap-3 px-5 py-2 text-xs">
      <span className="text-[var(--text-secondary)]">{formatDate(point.captured_at)}</span>
      <span className="flex items-center gap-1.5 font-mono">
        {prev !== null ? (
          <>
            <span className="text-[var(--text-tertiary)]">${prev.toFixed(4)}</span>
            <span className="text-[var(--text-tertiary)]" aria-hidden>
              →
            </span>
            <span>${curr.toFixed(4)}</span>
          </>
        ) : (
          <span>${curr.toFixed(4)}</span>
        )}
      </span>
      {delta === null ? (
        <span className="text-right text-[var(--text-tertiary)]">первая запись</span>
      ) : (
        <span
          className={`flex items-center justify-end gap-1 font-medium ${
            trendUp
              ? "text-[var(--danger)]"
              : trendDown
                ? "text-[var(--success-fg,#16a34a)]"
                : "text-[var(--text-tertiary)]"
          }`}
        >
          {trendUp && <TrendingUp className="size-3.5" aria-hidden />}
          {trendDown && <TrendingDown className="size-3.5" aria-hidden />}
          {delta > 0 ? "+" : ""}
          {delta.toFixed(2)}%
        </span>
      )}
    </li>
  );
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("ru", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
