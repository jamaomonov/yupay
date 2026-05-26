/** Searchable pickers used inside the mapping wizard.
 *
 * One file because these three pickers share the same shape (Combobox +
 * debounced query + TanStack Query fetch) — splitting them would just
 * triple the boilerplate. */

import { useQuery } from "@tanstack/react-query";
import { Box, Boxes, Gamepad2 } from "lucide-react";
import { useState } from "react";

import { Combobox } from "@/components/Combobox";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

import type { CatalogEntry, CatalogListOut, SkuPickerRow } from "./types";

// ---------------------------------------------------------------------------
// SKU picker
// ---------------------------------------------------------------------------

interface SkuPickerProps {
  value: SkuPickerRow | null;
  onChange: (next: SkuPickerRow | null) => void;
  disabled?: boolean;
  id?: string;
}

export function SkuPicker({ value, onChange, disabled, id }: SkuPickerProps) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 200);

  const { data, isLoading, isError } = useQuery<SkuPickerRow[]>({
    queryKey: qk.skuSearch(debounced),
    queryFn: () =>
      apiGet<SkuPickerRow[]>(
        debounced
          ? `/api/v1/admin/catalog/skus/search?q=${encodeURIComponent(debounced)}`
          : `/api/v1/admin/catalog/skus/search`,
      ),
    staleTime: 30_000,
  });

  return (
    <Combobox
      id={id}
      ariaLabel="SKU"
      value={value}
      onChange={onChange}
      items={data ?? []}
      query={query}
      onQueryChange={setQuery}
      loading={isLoading}
      errorMessage={isError ? "Не удалось загрузить SKU" : null}
      emptyMessage="SKU не найдены"
      disabled={disabled}
      placeholder="Выберите SKU…"
      keyFor={(r) => r.id}
      renderSelected={(r) => <SkuRow row={r} compact />}
      renderItem={(r) => <SkuRow row={r} />}
    />
  );
}

function SkuRow({ row, compact = false }: { row: SkuPickerRow; compact?: boolean }) {
  const denom = row.denomination ? ` · ${row.denomination}` : "";
  const kindIcon =
    row.product_kind === "top_up" ? (
      <Gamepad2 className="size-4 shrink-0 text-[var(--text-tertiary)]" aria-hidden />
    ) : (
      <Box className="size-4 shrink-0 text-[var(--text-tertiary)]" aria-hidden />
    );
  if (compact) {
    return (
      <span className="flex min-w-0 items-center gap-2">
        {kindIcon}
        <span className="min-w-0 truncate font-medium">{row.product_name}</span>
        {row.denomination && (
          <span className="shrink-0 text-[var(--text-secondary)]">{row.denomination}</span>
        )}
        <code className="shrink-0 text-[10px] text-[var(--text-tertiary)]">{row.sku_code}</code>
      </span>
    );
  }
  return (
    <div className="flex items-center gap-3">
      {kindIcon}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{row.product_name}</span>
          {!row.active && (
            <span className="rounded bg-[var(--bg-muted)] px-1.5 py-0.5 text-[10px] text-[var(--text-tertiary)]">
              inactive
            </span>
          )}
        </div>
        <div className="text-xs text-[var(--text-secondary)]">
          <code className="font-mono">{row.sku_code}</code>
          {denom}
          {row.region && ` · ${row.region}`}
        </div>
      </div>
      <div className="shrink-0 text-right font-mono text-xs text-[var(--text-tertiary)]">
        ${row.price_usd}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// G2B voucher / game pickers (both read from supplier_catalog_cache)
// ---------------------------------------------------------------------------

interface CatalogPickerProps {
  supplier: string;
  kind: "voucher" | "game";
  value: CatalogEntry | null;
  onChange: (next: CatalogEntry | null) => void;
  disabled?: boolean;
  id?: string;
}

export function CatalogPicker({
  supplier,
  kind,
  value,
  onChange,
  disabled,
  id,
}: CatalogPickerProps) {
  const [query, setQuery] = useState("");
  const debounced = useDebouncedValue(query, 200);

  const { data, isLoading, isError } = useQuery<CatalogListOut>({
    queryKey: qk.integrationCatalog({
      supplierSlug: supplier,
      kind,
      search: debounced,
    }),
    queryFn: () => {
      const params = new URLSearchParams({
        supplier_slug: supplier,
        kind,
        limit: "30",
      });
      if (debounced) params.set("search", debounced);
      return apiGet<CatalogListOut>(`/api/v1/admin/integrations/catalog?${params.toString()}`);
    },
    staleTime: 60_000,
  });

  const items = data?.items ?? [];

  return (
    <Combobox
      id={id}
      ariaLabel={kind === "voucher" ? "Ваучер G2B" : "Игра G2B"}
      value={value}
      onChange={onChange}
      items={items}
      query={query}
      onQueryChange={setQuery}
      loading={isLoading}
      errorMessage={isError ? "Не удалось загрузить каталог" : null}
      emptyMessage={
        items.length === 0 && debounced === ""
          ? "Кэш пуст — нажмите «Синхронизировать каталог» на странице поставщика."
          : "Ничего не найдено"
      }
      disabled={disabled}
      placeholder={kind === "voucher" ? "Выберите ваучер…" : "Выберите игру…"}
      keyFor={(e) => `${e.kind}-${e.external_id}`}
      renderSelected={(e) => <CatalogRow entry={e} kind={kind} compact />}
      renderItem={(e) => <CatalogRow entry={e} kind={kind} />}
    />
  );
}

function CatalogRow({
  entry,
  kind,
  compact = false,
}: {
  entry: CatalogEntry;
  kind: "voucher" | "game";
  compact?: boolean;
}) {
  const raw = entry.raw;
  const imageUrl = typeof raw.image_url === "string" ? raw.image_url : null;
  const stock = typeof raw.stock === "number" ? (raw.stock as number) : null;
  const unitPrice =
    typeof raw.unit_price === "number" || typeof raw.unit_price === "string"
      ? String(raw.unit_price)
      : null;

  const thumb =
    kind === "game" && imageUrl ? (
      <img
        src={imageUrl}
        alt=""
        className="size-7 shrink-0 rounded-sm object-cover"
        loading="lazy"
        draggable={false}
      />
    ) : (
      <Boxes className="size-5 shrink-0 text-[var(--text-tertiary)]" aria-hidden />
    );

  if (compact) {
    return (
      <span className="flex min-w-0 items-center gap-2">
        {kind === "game" && imageUrl ? (
              <img src={imageUrl} alt="" className="size-4 shrink-0 rounded-sm" />
        ) : null}
        <span className="min-w-0 truncate font-medium">{entry.title}</span>
        <code className="shrink-0 text-[10px] text-[var(--text-tertiary)]">
          {entry.external_id}
        </code>
      </span>
    );
  }

  return (
    <div className="flex items-center gap-3">
      {thumb}
      <div className="min-w-0 flex-1">
        <div className="truncate font-medium">{entry.title}</div>
        <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
          <code className="font-mono">{entry.external_id}</code>
          {unitPrice && <span>· ${unitPrice}</span>}
          {stock !== null && (
            <span className={stock > 0 ? "text-[var(--text-secondary)]" : "text-[var(--danger)]"}>
              · stock {stock.toString()}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
