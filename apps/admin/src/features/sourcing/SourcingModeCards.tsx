/** The four sourcing-mode cards on the single-SKU editor — split out of
 *  `SourcingPage.tsx` to keep that file under the 300-LOC soft limit
 *  (AGENTS.md §6). Self-contained: the card copy, the selection styling,
 *  and the "what auto resolves to for THIS sku" hint are all decided here
 *  from props alone. */

import { Hand, Sparkles, Truck, Warehouse } from "lucide-react";

import type { SourcingMode } from "./types";
import type { SkuPickerRow } from "@/features/integrations/types";

export interface ModeCard {
  value: SourcingMode;
  label: string;
  icon: typeof Sparkles;
  blurb: string;
}

export const MODE_CARDS: ModeCard[] = [
  {
    value: "auto",
    label: "Авто",
    icon: Sparkles,
    blurb: "Система решает по типу товара. Обычно ничего настраивать не нужно.",
  },
  {
    value: "force_supplier",
    label: "Только поставщик",
    icon: Truck,
    blurb: "Всегда выкупать у поставщика, минуя склад. Нужно выбрать какого.",
  },
  {
    value: "force_inventory",
    label: "Только склад",
    icon: Warehouse,
    blurb: "Выдавать только из склада кодов. Нет кодов — заказ упадёт в ошибку.",
  },
  {
    value: "manual",
    label: "Вручную",
    icon: Hand,
    blurb: "Без автоматики — заказ попадёт в очередь ручной выдачи оператору.",
  },
];

export function ModeOption({
  card,
  selected,
  autoHint,
  onSelect,
}: {
  card: ModeCard;
  selected: boolean;
  autoHint: string | null;
  onSelect: () => void;
}) {
  const Icon = card.icon;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={[
        "flex flex-col gap-1.5 rounded-md border p-3 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
        selected
          ? "border-[var(--accent)] bg-[var(--bg-accent-soft)]"
          : "border-[var(--border-default)] hover:bg-[var(--bg-muted)]",
      ].join(" ")}
    >
      <span className="flex items-center gap-2">
        <Icon className="size-4 text-[var(--accent)]" aria-hidden />
        <span className="font-medium">{card.label}</span>
      </span>
      <span className="text-xs text-[var(--text-secondary)]">{card.blurb}</span>
      {autoHint && (
        <span className="mt-0.5 rounded bg-[var(--bg-surface)] px-2 py-1 text-[11px] text-[var(--text-secondary)]">
          {autoHint}
        </span>
      )}
    </button>
  );
}

/** Human explanation of what "auto" resolves to for THIS sku. */
export function autoHintFor(sku: SkuPickerRow, mapping: { supplier_slug: string } | null): string {
  if (sku.product_kind === "top_up") {
    return mapping
      ? `Сейчас: поставщик ${mapping.supplier_slug} → при отказе ручная выдача.`
      : "Сейчас: ручная выдача (нет маппинга на поставщика).";
  }
  return mapping
    ? `Сейчас: склад → при пустом складе поставщик ${mapping.supplier_slug}.`
    : "Сейчас: склад → при пустом складе mock (dev) / ошибка (prod).";
}
