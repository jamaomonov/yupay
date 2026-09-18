/** "What happens for this SKU" panel on the single-SKU sourcing editor —
 *  split out of `SourcingPage.tsx` to keep that file under the 300-LOC
 *  soft limit (AGENTS.md §6). Two self-contained pieces: `SkuSummary`
 *  (product kind + mapping status chips) and `RoutePreview` (the live
 *  primary/fallback route the backend would take right now). */

import { ArrowRight, Boxes, Hand, Truck, Warehouse } from "lucide-react";

import type { SourcingDecisionOut } from "./types";
import type { SkuPickerRow } from "@/features/integrations/types";

import { Badge } from "@/components/Badge";

export function SkuSummary({
  sku,
  mapping,
}: {
  sku: SkuPickerRow;
  mapping: { supplier_slug: string } | null;
}) {
  const isTopUp = sku.product_kind === "top_up";
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md bg-[var(--bg-muted)] px-3 py-2 text-sm">
      <span className="font-medium">{sku.product_name}</span>
      <code className="text-xs text-[var(--text-secondary)]">{sku.sku_code}</code>
      <Badge
        tone={
          isTopUp
            ? "bg-[var(--info-soft)] text-[var(--info-fg)]"
            : "bg-[var(--bg-surface)] text-[var(--text-secondary)]"
        }
      >
        {isTopUp ? "игровой топ-ап" : "ваучер"}
      </Badge>
      {mapping ? (
        <Badge tone="bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]" dot>
          маппинг: {mapping.supplier_slug}
        </Badge>
      ) : (
        <Badge tone="bg-[var(--bg-surface)] text-[var(--text-tertiary)]">нет маппинга</Badge>
      )}
    </div>
  );
}

export function RoutePreview({
  decision,
  loading,
}: {
  decision: SourcingDecisionOut;
  loading: boolean;
}) {
  return (
    <div className="rounded-md border border-dashed border-[var(--border-default)] p-3">
      <div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
        Что произойдёт при оплате
        {loading && <span className="text-[var(--text-tertiary)]">· обновляем…</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <RouteNode route={decision.primary} primary />
        {decision.fallback && !decision.strict && (
          <>
            <span className="text-[var(--text-tertiary)]">
              <ArrowRight className="size-4" aria-hidden />
            </span>
            <span className="text-xs text-[var(--text-tertiary)]">если не вышло →</span>
            <RouteNode route={decision.fallback} primary={false} />
          </>
        )}
        {decision.strict && (
          <span className="text-xs text-[var(--text-tertiary)]">(без запасного варианта)</span>
        )}
      </div>
      {!decision.rule_present && (
        <p className="mt-2 text-[10px] text-[var(--text-tertiary)]">
          Режим «авто» — правило не задано явно.
        </p>
      )}
    </div>
  );
}

function RouteNode({ route, primary }: { route: string; primary: boolean }) {
  const { icon: Icon, label } = describeRoute(route);
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm",
        primary
          ? "bg-[var(--bg-accent-soft)] font-medium text-[var(--accent-soft-fg)]"
          : "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
      ].join(" ")}
    >
      <Icon className="size-4" aria-hidden />
      {label}
    </span>
  );
}

function describeRoute(route: string): { icon: typeof Boxes; label: string } {
  if (route === "inventory") return { icon: Warehouse, label: "Склад кодов" };
  const slug = route.startsWith("supplier:") ? route.slice("supplier:".length) : route;
  if (slug === "manual") return { icon: Hand, label: "Ручная выдача" };
  if (slug === "g2b") return { icon: Truck, label: "Поставщик G2Bulk" };
  if (slug === "mock") return { icon: Boxes, label: "Mock (dev)" };
  return { icon: Truck, label: `Поставщик ${slug}` };
}
