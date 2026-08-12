/** Card visualising one SKU's supplier-cost history.
 *
 * Mounted on the SKU edit page so the operator can see at a glance
 * whether the cost has been drifting since they last touched the
 * mapping. Reads ``GET /admin/integrations/sku-prices/{sku_id}/history``
 * and renders the latest 30 points as a Sparkline.
 *
 * Hidden entirely when the SKU has no history — operators looking at a
 * fresh SKU shouldn't see an empty chart they have to interpret. The full,
 * unclipped history (up to the server's 500-point ceiling) lives behind the
 * "Вся история" button in {@link SkuPriceHistoryModal}. */

import { useQuery } from "@tanstack/react-query";
import { History, TrendingDown, TrendingUp } from "lucide-react";
import { useState } from "react";

import { SkuPriceHistoryModal } from "./SkuPriceHistoryModal";

import type { PriceHistoryListOut } from "./types";

import { Sparkline } from "@/components/Sparkline";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

interface Props {
  skuId: string;
  skuCode: string;
}

export function SkuPriceHistoryCard({ skuId, skuCode }: Props) {
  const [modalOpen, setModalOpen] = useState(false);
  const query = useQuery<PriceHistoryListOut>({
    queryKey: qk.skuPriceHistory(skuId),
    queryFn: () =>
      apiGet<PriceHistoryListOut>(
        `/api/v1/admin/integrations/sku-prices/${skuId}/history?limit=30`,
      ),
    staleTime: 60_000,
  });

  if (query.isLoading) {
    return (
      <section className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4">
        <header className="mb-2 text-xs uppercase tracking-wide text-[var(--text-tertiary)]">
          История цены поставщика
        </header>
        <p className="text-xs text-[var(--text-tertiary)]">Загрузка…</p>
      </section>
    );
  }

  const items = query.data?.items ?? [];
  if (items.length === 0) return null;

  // History is newest-first; sparkline wants oldest-first.
  const ordered = [...items].reverse();
  const values = ordered.map((p) => Number.parseFloat(p.cost_usdt));
  const first = values[0]!;
  const last = values[values.length - 1]!;
  const delta = first === 0 ? 0 : ((last - first) / first) * 100;
  const trendUp = delta > 0;

  return (
    <section className="space-y-3 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4">
      <header className="flex items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-medium">История цены поставщика</h3>
          <p className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
            {items.length.toString()} точек · последняя{" "}
            {formatDate(ordered[ordered.length - 1]!.captured_at)}
          </p>
        </div>
        <DeltaBadge delta={delta} trendUp={trendUp} />
      </header>

      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-col">
          <span className="text-xs text-[var(--text-tertiary)]">Текущая</span>
          <span className="font-mono text-lg">${last.toFixed(4)}</span>
        </div>
        <Sparkline values={values} width={220} height={48} ariaLabel="История цены" />
        <div className="flex flex-col text-right">
          <span className="text-xs text-[var(--text-tertiary)]">Первая</span>
          <span className="font-mono text-sm text-[var(--text-secondary)]">
            ${first.toFixed(4)}
          </span>
        </div>
      </div>

      <button
        type="button"
        onClick={() => {
          setModalOpen(true);
        }}
        className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
      >
        <History className="size-3.5" aria-hidden />
        Вся история
      </button>

      {modalOpen && (
        <SkuPriceHistoryModal
          skuId={skuId}
          skuCode={skuCode}
          onClose={() => {
            setModalOpen(false);
          }}
        />
      )}
    </section>
  );
}

function DeltaBadge({ delta, trendUp }: { delta: number; trendUp: boolean }) {
  if (Math.abs(delta) < 0.01) {
    return (
      <span className="rounded-full bg-[var(--bg-muted)] px-2 py-0.5 text-xs text-[var(--text-secondary)]">
        без изменений
      </span>
    );
  }
  const Icon = trendUp ? TrendingUp : TrendingDown;
  const tone = trendUp ? "text-[var(--danger)]" : "text-[var(--success-fg,#16a34a)]";
  const sign = delta > 0 ? "+" : "";
  return (
    <span className={`flex items-center gap-1 text-sm font-medium ${tone}`}>
      <Icon className="size-4" aria-hidden />
      {sign}
      {delta.toFixed(2)}%
    </span>
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
