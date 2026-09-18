/** Search/mode/supplier filter row for `RulesTable` — split out to keep
 *  `RulesTable.tsx` under the 300-LOC soft limit (AGENTS.md §6), same
 *  precedent as `BrandSourcingToolbar` for `BrandSourcingPage`. Purely
 *  controlled: every value and change handler comes from props; the mode
 *  label map lives in `RulesTable.tsx` (it also colours `ModeBadge` there)
 *  and is passed down rather than duplicated. */

import { Input, Select } from "@yupay/ui";

import type { SourcingMode } from "./types";

export interface RulesTableFiltersProps {
  search: string;
  onSearchChange: (value: string) => void;
  modeFilter: SourcingMode | "";
  onModeFilterChange: (value: SourcingMode | "") => void;
  modeLabels: Record<SourcingMode, string>;
  supplierFilter: string;
  onSupplierFilterChange: (value: string) => void;
  supplierOptions: string[];
}

export function RulesTableFilters({
  search,
  onSearchChange,
  modeFilter,
  onModeFilterChange,
  modeLabels,
  supplierFilter,
  onSupplierFilterChange,
  supplierOptions,
}: RulesTableFiltersProps) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <div className="min-w-48 flex-1">
        <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
          Поиск
        </label>
        <Input
          value={search}
          onChange={(e) => {
            onSearchChange(e.target.value);
          }}
          placeholder="Бренд, товар, код, номинал…"
        />
      </div>
      <div>
        <label
          htmlFor="sourcing-rules-mode-filter"
          className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]"
        >
          Режим
        </label>
        <Select
          id="sourcing-rules-mode-filter"
          value={modeFilter}
          onChange={(e) => {
            // Narrowing a DOM value: every <option> below is either "" or a
            // literal SourcingMode, so the select can never produce
            // anything else (same precedent as BrandSourcingPage's mode
            // select).
            onModeFilterChange(e.target.value as SourcingMode | "");
          }}
          containerClassName="w-44"
        >
          <option value="">Все режимы</option>
          {(Object.keys(modeLabels) as SourcingMode[]).map((m) => (
            <option key={m} value={m}>
              {modeLabels[m]}
            </option>
          ))}
        </Select>
      </div>
      <div>
        <label
          htmlFor="sourcing-rules-supplier-filter"
          className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]"
        >
          Поставщик
        </label>
        <Select
          id="sourcing-rules-supplier-filter"
          value={supplierFilter}
          onChange={(e) => {
            onSupplierFilterChange(e.target.value);
          }}
          containerClassName="w-40"
        >
          <option value="">Все поставщики</option>
          {supplierOptions.map((slug) => (
            <option key={slug} value={slug}>
              {slug}
            </option>
          ))}
        </Select>
      </div>
    </div>
  );
}
