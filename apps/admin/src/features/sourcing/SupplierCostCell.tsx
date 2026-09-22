/** One supplier's cost cell inside `BrandSourcingTable` — split out to keep
 *  that file under the 300-LOC soft limit (AGENTS.md §6). Self-contained:
 *  the cheapest-cost badge, the "no mapping" / "no price yet" gaps, the
 *  current-route label (including the fallback-only nuance for a voucher
 *  SKU), and the switch button's warehouse-bypass warning are all decided
 *  from this cell's own props. */

import type { SourcingBrandSupplierOut } from "./types";

import { Badge } from "@/components/Badge";
import { formatMoneyValue } from "@/lib/money";

export function SupplierCell({
  slug,
  supplier,
  isCurrentRoute,
  isFallbackRoute,
  wouldBypassInventory,
  isCheapest,
  pending,
  onSwitch,
}: {
  slug: string;
  supplier: SourcingBrandSupplierOut | undefined;
  isCurrentRoute: boolean;
  /** True when this cell IS the current route, and it's current only as
   *  the code warehouse's fallback (`primary === "inventory"`), not as the
   *  row's primary route — so "текущий" alone would read as "we buy from
   *  here first", which is backwards for a voucher SKU. */
  isFallbackRoute: boolean;
  /** True when clicking this cell's own switch button would take the code
   *  warehouse out of routing for this SKU entirely (Important #1) — i.e.
   *  the row's automatic route goes through inventory first today. */
  wouldBypassInventory: boolean;
  isCheapest: boolean;
  pending: boolean;
  onSwitch: () => void;
}) {
  if (!supplier?.has_active_mapping) {
    // "Not offerable" must be visible as a reason, not just an absent or
    // disabled control (spec §6 + brief) — the gap is the reason.
    return <td className="py-2 pr-3 text-[11px] text-[var(--text-tertiary)]">нет маппинга</td>;
  }
  // `has_active_mapping` and `latest_cost_usdt` come from independent
  // backend sources (the mapping row vs. price history) — a freshly
  // created mapping, or a supplier like waxpeer that never records price
  // rows by design, is mapped with an unknown cost. A real cost can never
  // be "0" (a positive-cost CHECK constraint on the price table), so that
  // used to render a number the system cannot produce and let the operator
  // force a supplier whose price is simply unmeasured, with no badge to
  // warn them off it.
  const cost = supplier.latest_cost_usdt;
  return (
    <td className={["py-2 pr-3", isCheapest ? "bg-[var(--success-soft)]" : ""].join(" ")}>
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-1.5">
          {cost !== null ? (
            <>
              {/* Cheapest-supplier comparison decides at 6-decimal
                  precision (`cheapestSlugs`) but this cell only shows 2 —
                  the raw value in `title` lets a near-tie explain itself
                  on hover instead of two different-looking "дешевле всех"
                  verdicts for what looks like the same number. */}
              <span title={costTitle(cost, supplier.cost_source)}>
                {formatMoneyValue(cost, "USDT")} USDT
              </span>
              {isCheapest && (
                <Badge tone="bg-[var(--success-soft)] text-[var(--success-fg)]">дешевле всех</Badge>
              )}
            </>
          ) : (
            <span
              className="text-[var(--text-tertiary)]"
              title="Маппинг активен, но цена ещё не снята с этого поставщика"
            >
              — <span className="text-[10px]">цена не снята</span>
            </span>
          )}
        </span>
        {/* `cost_source === "current"` means there is no history row to
            date — `captured_at` is `null` by contract, so the date line
            below would otherwise just vanish, leaving a captured-looking
            number with no visible difference from a real capture. Say what
            it actually is instead: the SKU's own `cost_usdt`, not a
            point-in-time price snapshot.

            Gated on `cost !== null`: the backend contract pairs
            `cost_source: "current"` with a non-null `latest_cost_usdt`, but
            this cell still has to render *something* sane if that
            combination ever slips through anyway — and "текущая цена SKU"
            right under "цена не снята" would claim a current price the
            cell isn't showing. */}
        {cost !== null &&
          (supplier.cost_source === "current" ? (
            <span className="text-[10px] text-[var(--text-tertiary)]">текущая цена SKU</span>
          ) : (
            supplier.captured_at && (
              <span className="text-[10px] text-[var(--text-tertiary)]">
                {new Date(supplier.captured_at).toLocaleDateString("ru", {
                  day: "2-digit",
                  month: "2-digit",
                  year: "2-digit",
                })}
              </span>
            )
          ))}
        {/* Per-supplier stock. `Sku.supplier_stock` holds only the routed
            supplier's number, which is exactly the one an operator
            comparing suppliers already knows — the useful fact is that the
            supplier we are pinned to is empty while another is not.
            `null` stays blank rather than rendering "0": unknown and sold
            out are different, and conflating them would push someone off a
            supplier that can actually deliver. */}
        {supplier.stock !== null && (
          <span
            className={[
              "text-[10px]",
              supplier.stock === 0 ? "text-[var(--danger-fg)]" : "text-[var(--text-tertiary)]",
            ].join(" ")}
            title={
              supplier.stock_at
                ? `Остаток по данным каталога от ${new Date(supplier.stock_at).toLocaleString("ru")}`
                : undefined
            }
          >
            {supplier.stock === 0 ? "нет в наличии" : `в наличии: ${supplier.stock.toString()}`}
          </span>
        )}
        {isCurrentRoute ? (
          <span className="text-[10px] text-[var(--accent)]">
            {isFallbackRoute ? "текущий (запасной, после склада)" : "текущий"}
          </span>
        ) : (
          <button
            type="button"
            onClick={onSwitch}
            disabled={pending}
            aria-label={`Переключить на ${slug}`}
            title={switchButtonTitle(wouldBypassInventory, cost === null)}
            className={[
              "w-fit rounded border px-1.5 py-0.5 text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              wouldBypassInventory
                ? "border-[var(--warning-fg)] text-[var(--warning-fg)] hover:bg-[var(--warning-soft)]"
                : "border-[var(--border-default)] text-[var(--text-secondary)] hover:bg-[var(--bg-muted)]",
            ].join(" ")}
          >
            {wouldBypassInventory ? "в обход склада →" : "сюда →"}
          </button>
        )}
      </div>
    </td>
  );
}

/** Hover tooltip for a supplier's cost value — flags a `"current"` cost as
 *  the SKU's own `cost_usdt` rather than a captured price, mirroring the
 *  visible note below the number. */
function costTitle(cost: string, source: "history" | "current" | null): string {
  if (source === "current") return `${cost} USDT (текущая цена SKU, история не записана)`;
  return `${cost} USDT`;
}

/** Tooltip for a supplier cell's own switch button — states the
 *  warehouse-bypass consequence first (Important #1) since it is the one
 *  that changes what actually happens on checkout, then the unmeasured-cost
 *  caveat that already existed. */
function switchButtonTitle(
  wouldBypassInventory: boolean,
  costUnknown: boolean,
): string | undefined {
  const parts: string[] = [];
  if (wouldBypassInventory) {
    parts.push("Склад кодов перестанет использоваться для этого SKU — коды в остатке не тронут.");
  }
  if (costUnknown) {
    parts.push("Цена не снята — переключение вслепую.");
  }
  return parts.length > 0 ? parts.join(" ") : undefined;
}
