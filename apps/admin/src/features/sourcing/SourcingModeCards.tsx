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
  disabledReason,
  onSelect,
}: {
  card: ModeCard;
  selected: boolean;
  autoHint: string | null;
  /** Non-null when this card must not be offered for the current SKU — the
   *  card renders disabled and shows this text in place of (well, beside)
   *  its usual blurb, same treatment `SupplierCell` already gives a
   *  supplier with no active mapping: the gap is visible text, not merely
   *  an absent or disabled control. */
  disabledReason: string | null;
  onSelect: () => void;
}) {
  const Icon = card.icon;
  const disabled = disabledReason !== null;
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onSelect}
      disabled={disabled}
      aria-pressed={selected}
      className={[
        "flex flex-col gap-1.5 rounded-md border p-3 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
        "disabled:cursor-not-allowed disabled:opacity-50",
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
      {disabledReason && (
        <span className="mt-0.5 rounded bg-[var(--bg-surface)] px-2 py-1 text-[11px] text-[var(--danger)]">
          {disabledReason}
        </span>
      )}
      {autoHint && !disabled && (
        <span className="mt-0.5 rounded bg-[var(--bg-surface)] px-2 py-1 text-[11px] text-[var(--text-secondary)]">
          {autoHint}
        </span>
      )}
    </button>
  );
}

/** Why a mode card must not be offered for THIS sku — `null` when the card
 *  is offerable. Today this only guards `force_inventory` against a
 *  `top_up` SKU: the code warehouse holds voucher codes, so a top-up SKU
 *  has nothing there a payment could ever be fulfilled from — offering the
 *  card would let an operator route an order at a warehouse that can never
 *  fill it. */
export function disabledReasonFor(mode: SourcingMode, sku: SkuPickerRow): string | null {
  if (mode === "force_inventory" && sku.product_kind === "top_up") {
    return "Топ-ап нельзя выдать со склада кодов — там только ваучеры.";
  }
  return null;
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
