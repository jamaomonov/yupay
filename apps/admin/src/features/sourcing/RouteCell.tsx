/** The «Маршрут сейчас» cell of `BrandSourcingTable` — split out to keep that
 *  file under the 300-LOC soft limit. It answers one question first: who
 *  decides this row's supplier (smart routing, a pin, the legacy default, the
 *  manual queue or the warehouse), then offers the actions that fit that state. */

import {
  canHandToSmart,
  describeRoute,
  ROUTE_STATUS,
  type RouteStatus,
} from "./brandSourcingFormat";

import type { SourcingBrandSkuOut, SourcingMode } from "./types";

import { Badge } from "@/components/Badge";

export interface RouteCellProps {
  item: SourcingBrandSkuOut;
  status: RouteStatus;
  failure: string | undefined;
  inventoryDisabledReason: string | null;
  disabled: boolean;
  onSwitchOne: (skuId: string, mode: SourcingMode, supplierSlug: string | null) => void;
  onManagedOne: (skuId: string, managed: boolean) => void;
}

export function RouteCell({
  item,
  status,
  failure,
  inventoryDisabledReason,
  disabled,
  onSwitchOne,
  onManagedOne,
}: RouteCellProps) {
  return (
    <td className="py-2 pr-3">
      <div className="flex flex-col gap-1">
        <Badge tone={ROUTE_STATUS[status].tone} className="self-start">
          {ROUTE_STATUS[status].label}
        </Badge>
        <span>{describeRoute(item.primary)}</span>
        <span className="text-[10px] text-[var(--text-tertiary)]">{ROUTE_STATUS[status].hint}</span>
        <div className="flex flex-wrap gap-1">
          {status === "smart" ? (
            <QuickModeButton
              label="закрепить"
              title="Оставить этого поставщика; автовыбор перестанет менять"
              onClick={() => {
                onManagedOne(item.sku_id, false);
              }}
              disabled={disabled}
            />
          ) : (
            canHandToSmart(item) && (
              <QuickModeButton
                label="отдать автовыбору"
                title="Раз в час система сама будет выбирать поставщика"
                onClick={() => {
                  onManagedOne(item.sku_id, true);
                }}
                disabled={disabled}
              />
            )
          )}
          {inventoryDisabledReason ? (
            // Not offerable — the gap is visible text, not just
            // an absent control, same treatment `SupplierCell`
            // gives a supplier with no active mapping
            // ("нет маппинга"). The backend rejects this mode
            // for a top_up SKU outright; this only keeps the
            // operator from round-tripping a 422 to find out.
            <span
              className="text-[11px] text-[var(--text-tertiary)]"
              title="Топ-ап нельзя выдать со склада кодов — там нет кодов, которые можно списать за пополнение"
            >
              склад: {inventoryDisabledReason}
            </span>
          ) : (
            <QuickModeButton
              label="склад"
              onClick={() => {
                onSwitchOne(item.sku_id, "force_inventory", null);
              }}
              disabled={disabled}
            />
          )}
          {status !== "manual" && (
            <QuickModeButton
              label="ручная выдача"
              title="Заказы этого номинала будет выдавать оператор вручную"
              onClick={() => {
                if (
                  window.confirm(
                    `${item.sku_code}: перевести на ручную выдачу оператором? ` +
                      "Поставщик перестанет получать эти заказы.",
                  )
                ) {
                  onSwitchOne(item.sku_id, "manual", null);
                }
              }}
              disabled={disabled}
            />
          )}
        </div>
        {failure && <p className="text-[11px] text-[var(--danger)]">{failure}</p>}
      </div>
    </td>
  );
}

function QuickModeButton({
  label,
  title,
  onClick,
  disabled,
}: {
  label: string;
  title?: string;
  onClick: () => void;
  disabled: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="rounded border border-[var(--border-default)] px-1.5 py-0.5 text-[11px] text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-muted)] disabled:cursor-not-allowed disabled:opacity-50"
    >
      {label}
    </button>
  );
}
