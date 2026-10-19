/** Brand picker + bulk-mode controls for `BrandSourcingPage` — split out to
 *  keep that file under the 300-LOC soft limit (AGENTS.md §6). Purely
 *  controlled: every value and every change handler comes from props, and
 *  the confirmation prompt (`bulkConfirmMessage`, `./brandSourcingFormat.ts`)
 *  and the write itself stay owned by the page, which is what needs
 *  `overviewQuery`'s `items` to know who a bulk switch would take off the
 *  code warehouse. */

import { Button, Select } from "@yupay/ui";
import { useState } from "react";

import { BULK_SUPPLIER_OPTIONS } from "./supplierOptions";

import type { SourcingMode } from "./types";
import type { Brand } from "@/features/catalog/types";

import { Combobox } from "@/components/Combobox";
import { RESERVE_SUPPLIERS } from "@/features/integrations/types";
import { matchesText } from "@/lib/textSearch";

export interface BrandSourcingToolbarProps {
  brands: Brand[] | undefined;
  brandSlug: string | null;
  onBrandChange: (slug: string) => void;
  selectedCount: number;
  bulkMode: SourcingMode;
  onBulkModeChange: (mode: SourcingMode) => void;
  bulkSupplier: string;
  onBulkSupplierChange: (slug: string) => void;
  canApply: boolean;
  applyPending: boolean;
  onApply: () => void;
}

function brandName(b: Brand): string {
  return b.translations.find((t) => t.locale === "ru")?.name ?? b.slug;
}

export function BrandSourcingToolbar({
  brands,
  brandSlug,
  onBrandChange,
  selectedCount,
  bulkMode,
  onBulkModeChange,
  bulkSupplier,
  onBulkSupplierChange,
  canApply,
  applyPending,
  onApply,
}: BrandSourcingToolbarProps) {
  const [brandQuery, setBrandQuery] = useState("");
  const selectedBrand = brands?.find((b) => b.slug === brandSlug) ?? null;
  const matchingBrands = (brands ?? []).filter((b) =>
    matchesText(brandQuery, [b.slug, ...b.translations.map((t) => t.name)]),
  );

  return (
    <section className="flex flex-wrap items-end gap-4 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <div>
        <label
          htmlFor="brand-sourcing-brand-select"
          className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]"
        >
          Бренд
        </label>
        <div className="w-72">
          <Combobox<Brand>
            id="brand-sourcing-brand-select"
            ariaLabel="Бренд"
            value={selectedBrand}
            onChange={(b) => {
              onBrandChange(b?.slug ?? "");
            }}
            items={matchingBrands}
            query={brandQuery}
            onQueryChange={setBrandQuery}
            loading={brands === undefined}
            emptyMessage="Бренд не найден"
            placeholder="— Выбери бренд —"
            keyFor={(b) => b.id}
            renderSelected={(b) => <span className="truncate">{brandName(b)}</span>}
            renderItem={(b) => (
              <span className="flex min-w-0 items-center gap-2">
                <span className="truncate">{brandName(b)}</span>
                <code className="shrink-0 text-[10px] text-[var(--text-tertiary)]">{b.slug}</code>
              </span>
            )}
          />
        </div>
      </div>

      {selectedCount > 0 && (
        <>
          <div>
            <label
              htmlFor="brand-sourcing-mode-select"
              className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]"
            >
              Режим для {selectedCount.toString()} SKU
            </label>
            <Select
              id="brand-sourcing-mode-select"
              value={bulkMode}
              onChange={(e) => {
                // Narrowing a DOM value: every <option> below is a literal
                // SourcingMode, so the select can never produce anything else.
                onBulkModeChange(e.target.value as SourcingMode);
              }}
              containerClassName="w-48"
            >
              <option value="force_supplier">Только поставщик</option>
              <option value="force_inventory">Только склад</option>
              <option value="manual">Вручную</option>
              <option value="auto">Авто</option>
            </Select>
          </div>
          {bulkMode === "force_supplier" && (
            <div>
              <label
                htmlFor="brand-sourcing-supplier-select"
                className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]"
              >
                Поставщик
              </label>
              <Select
                id="brand-sourcing-supplier-select"
                value={bulkSupplier}
                onChange={(e) => {
                  onBulkSupplierChange(e.target.value);
                }}
                containerClassName="w-40"
              >
                {BULK_SUPPLIER_OPTIONS.map((s) => (
                  <option key={s.slug} value={s.slug}>
                    {s.label}
                    {RESERVE_SUPPLIERS.has(s.slug) ? " · резерв" : ""}
                  </option>
                ))}
              </Select>
            </div>
          )}
          <Button onClick={onApply} disabled={!canApply}>
            {applyPending ? "Переключаем…" : `Применить к ${selectedCount.toString()}`}
          </Button>
        </>
      )}
    </section>
  );
}
