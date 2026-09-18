/** The brand-overview table itself — one row per active SKU, with a
 *  cost column per candidate supplier and a per-row switch control.
 *
 *  Split out of `BrandSourcingPage.tsx` to keep both files under the
 *  300-LOC soft limit (AGENTS.md §6) and because the row/column logic
 *  (cheapest-cost highlighting, the "no mapping" gap, the reserve-supplier
 *  note) is a self-contained concern the page component does not need to
 *  know about. */

import { useMemo } from "react";

import {
  bypassesInventory,
  cheapestSlugs,
  describeRoute,
  isCurrentSupplierRoute,
  marginPercent,
  supplierLabel,
} from "./brandSourcingFormat";
import { SupplierCell } from "./SupplierCostCell";

import type { SourcingBrandSkuOut, SourcingMode } from "./types";

import { EmptyState, TableSkeleton } from "@/components/States";
import { RESERVE_SUPPLIERS } from "@/features/integrations/types";
import { formatMoneyValue } from "@/lib/money";

export interface BrandSourcingTableProps {
  items: SourcingBrandSkuOut[];
  loading: boolean;
  selected: ReadonlySet<string>;
  onToggle: (skuId: string) => void;
  onToggleAll: () => void;
  /** Fires a single-SKU switch through the same bulk endpoint the header
   *  action uses (`sku_ids: [skuId]`) — "a row switches from its own
   *  control" per the design (§6). */
  onSwitchOne: (skuId: string, mode: SourcingMode, supplierSlug: string | null) => void;
  /** True while the header's bulk mutation is in flight — disables every
   *  row's controls, since a bulk write can touch any of them. */
  pending: boolean;
  /** SKU ids with their own per-row switch in flight right now — disables
   *  only that row's controls, independent of `pending`. */
  pendingSkuIds: ReadonlySet<string>;
  /** Per-SKU failure reason from the most recent switch attempt — cleared
   *  by the page once a fresh attempt starts. */
  failures: ReadonlyMap<string, string>;
  /** SKUs whose route just changed in this browser session, so `cost_usdt`
   *  and the margin derived from it still reflect the *previous* route —
   *  a switch writes only `sku_sourcing_rules`; the cost column is repriced
   *  by the hourly job, not by the switch itself (whole-branch review,
   *  Important #4). Renders an inline "не обновилась" note instead of
   *  letting the operator read a stale cost as current. */
  staleCostSkuIds: ReadonlySet<string>;
}

export function BrandSourcingTable({
  items,
  loading,
  selected,
  onToggle,
  onToggleAll,
  onSwitchOne,
  pending,
  pendingSkuIds,
  failures,
  staleCostSkuIds,
}: BrandSourcingTableProps) {
  // Every item of one response carries the same candidate supplier set
  // (`brand_overview.get_brand_overview` computes it once per request) —
  // union across items anyway rather than trust the first row, so a future
  // per-row divergence degrades to "extra column" instead of "missing one".
  const supplierSlugs = useMemo(() => {
    const seen = new Set<string>();
    for (const item of items) {
      for (const s of item.suppliers) seen.add(s.supplier_slug);
    }
    return [...seen].sort((a, b) => a.localeCompare(b));
  }, [items]);

  if (loading) {
    return <TableSkeleton rows={6} columns={4 + supplierSlugs.length} />;
  }
  if (items.length === 0) {
    return <EmptyState title="У этого бренда нет активных SKU." tone="muted" />;
  }

  const allSelected = items.length > 0 && items.every((i) => selected.has(i.sku_id));

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <table className="w-full text-sm">
        <thead className="bg-[var(--bg-muted)] text-left text-xs text-[var(--text-secondary)]">
          <tr>
            <th className="w-10 py-2 pl-3">
              <input
                type="checkbox"
                aria-label="Выбрать все"
                checked={allSelected}
                onChange={onToggleAll}
              />
            </th>
            <th className="py-2">SKU</th>
            <th className="py-2">Маршрут сейчас</th>
            <th className="py-2">Наша цена</th>
            {supplierSlugs.map((slug) => (
              <th key={slug} className="py-2 pr-3">
                {supplierLabel(slug)}
                {RESERVE_SUPPLIERS.has(slug) && (
                  <span className="ml-1 text-[10px] font-normal text-[var(--text-tertiary)]">
                    резерв
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const cheapest = cheapestSlugs(item.suppliers);
            const margin = marginPercent(item.price_usd, item.cost_usdt);
            const failure = failures.get(item.sku_id);
            const rowPending = pending || pendingSkuIds.has(item.sku_id);
            return (
              <tr key={item.sku_id} className="border-t border-[var(--border-default)] align-top">
                <td className="py-2 pl-3">
                  <input
                    type="checkbox"
                    aria-label={`Выбрать ${item.sku_code}`}
                    checked={selected.has(item.sku_id)}
                    onChange={() => {
                      onToggle(item.sku_id);
                    }}
                  />
                </td>
                <td className="py-2 pr-3">
                  <div className="flex flex-col">
                    <span className="font-medium">{item.product_slug}</span>
                    <code className="text-xs text-[var(--text-secondary)]">
                      {item.sku_code}
                      {item.denomination && ` · ${item.denomination}`}
                    </code>
                  </div>
                </td>
                <td className="py-2 pr-3">
                  <div className="flex flex-col gap-1">
                    <span>{describeRoute(item.primary)}</span>
                    <span className="text-[10px] text-[var(--text-tertiary)]">
                      {item.rule_present ? "явное правило" : "авто"}
                    </span>
                    <div className="flex flex-wrap gap-1">
                      <QuickModeButton
                        label="авто"
                        onClick={() => {
                          onSwitchOne(item.sku_id, "auto", null);
                        }}
                        disabled={rowPending}
                      />
                      <QuickModeButton
                        label="склад"
                        onClick={() => {
                          onSwitchOne(item.sku_id, "force_inventory", null);
                        }}
                        disabled={rowPending}
                      />
                      <QuickModeButton
                        label="вручную"
                        onClick={() => {
                          onSwitchOne(item.sku_id, "manual", null);
                        }}
                        disabled={rowPending}
                      />
                    </div>
                    {failure && <p className="text-[11px] text-[var(--danger)]">{failure}</p>}
                  </div>
                </td>
                <td className="py-2 pr-3">
                  <div className="flex flex-col">
                    <span>{formatMoneyValue(item.price_usd, "USD")} $</span>
                    {margin !== null && (
                      <span className="text-[10px] text-[var(--text-tertiary)]">
                        маржа ~{margin}%
                      </span>
                    )}
                    {staleCostSkuIds.has(item.sku_id) && (
                      <span
                        className="text-[10px] font-medium text-[var(--warning-fg)]"
                        title="Маршрут переключён, но cost_usdt пересчитывает почасовое обновление цен — значение выше ещё от прежнего поставщика."
                      >
                        цена не обновилась — обновится в течение часа
                      </span>
                    )}
                  </div>
                </td>
                {supplierSlugs.map((slug) => {
                  const supplier = item.suppliers.find((s) => s.supplier_slug === slug);
                  return (
                    <SupplierCell
                      key={slug}
                      slug={slug}
                      supplier={supplier}
                      isCurrentRoute={isCurrentSupplierRoute(item, slug)}
                      isFallbackRoute={
                        item.primary === "inventory" && item.fallback === `supplier:${slug}`
                      }
                      wouldBypassInventory={bypassesInventory(item)}
                      isCheapest={cheapest.has(slug)}
                      pending={rowPending}
                      onSwitch={() => {
                        onSwitchOne(item.sku_id, "force_supplier", slug);
                      }}
                    />
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function QuickModeButton({
  label,
  onClick,
  disabled,
}: {
  label: string;
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="rounded border border-[var(--border-default)] px-1.5 py-0.5 text-[11px] text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-muted)] disabled:cursor-not-allowed disabled:opacity-50"
    >
      {label}
    </button>
  );
}
