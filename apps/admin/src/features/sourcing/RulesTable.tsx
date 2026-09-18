/** The explicit-rules table on `SourcingPage` — searchable and filterable.
 *
 * Split out of `SourcingPage.tsx` (already over its 300-LOC soft limit
 * before this) so the single-SKU editor stays a one-off-edit tool while
 * this table carries its own concern: finding a rule among many without
 * decoding a SKU code by eye. The single-SKU editor is deliberately left
 * alone — a one-off edit should not require choosing a brand first, which
 * is why `BrandSourcingPage` (the brand-scoped bulk screen) is a separate
 * page rather than a replacement for this table. */

import { useQuery } from "@tanstack/react-query";
import { Button, Input, Select } from "@yupay/ui";
import { useMemo, useState } from "react";

import type { SourcingMode, SourcingRuleOut } from "./types";
import type { Brand, Product, Sku } from "@/features/catalog/types";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

function rname(obj: { translations: { locale: string; name: string }[] } | undefined): string {
  if (!obj) return "";
  return obj.translations.find((t) => t.locale === "ru")?.name ?? "";
}

interface EnrichedRule extends SourcingRuleOut {
  brandName: string;
  productSlug: string;
  denomination: string | null;
}

export interface RulesTableProps {
  rules: SourcingRuleOut[];
  loading: boolean;
  onDelete: (skuId: string) => void;
}

const MODE_LABELS: Record<SourcingMode, string> = {
  auto: "авто",
  force_inventory: "только склад",
  force_supplier: "только поставщик",
  manual: "вручную",
};

export function RulesTable({ rules, loading, onDelete }: RulesTableProps) {
  const [search, setSearch] = useState("");
  const [supplierFilter, setSupplierFilter] = useState("");
  const [modeFilter, setModeFilter] = useState("");

  const skusQuery = useQuery<Sku[]>({
    queryKey: qk.skus(),
    queryFn: () => apiGet<Sku[]>("/api/v1/admin/catalog/skus"),
  });
  const productsQuery = useQuery<Product[]>({
    queryKey: qk.products(),
    queryFn: () => apiGet<Product[]>("/api/v1/admin/catalog/products"),
  });
  const brandsQuery = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });

  const enriched = useMemo<EnrichedRule[]>(() => {
    const skuById = new Map((skusQuery.data ?? []).map((s) => [s.id, s]));
    const productById = new Map((productsQuery.data ?? []).map((p) => [p.id, p]));
    const brandById = new Map((brandsQuery.data ?? []).map((b) => [b.id, b]));
    return rules.map((rule) => {
      const sku = skuById.get(rule.sku_id);
      const product = sku ? productById.get(sku.product_id) : undefined;
      const brand = product ? brandById.get(product.brand_id) : undefined;
      return {
        ...rule,
        brandName: rname(brand),
        productSlug: product?.slug ?? "",
        denomination: sku?.denomination ?? null,
      };
    });
  }, [rules, skusQuery.data, productsQuery.data, brandsQuery.data]);

  // Supplier filter options come from the data itself, not a static list —
  // a supplier nobody has a rule for yet has nothing to filter to, and this
  // never drifts from what `FULFILMENT_ROUTES` offers on the editor above.
  const supplierOptions = useMemo(() => {
    const seen = new Set<string>();
    for (const r of rules) if (r.supplier_slug) seen.add(r.supplier_slug);
    return [...seen].sort((a, b) => a.localeCompare(b));
  }, [rules]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return enriched.filter((r) => {
      if (modeFilter && r.mode !== modeFilter) return false;
      if (supplierFilter && r.supplier_slug !== supplierFilter) return false;
      if (q.length === 0) return true;
      const haystack = [r.brandName, r.productSlug, r.sku_code, r.denomination ?? ""]
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [enriched, search, modeFilter, supplierFilter]);

  const columns: Column<EnrichedRule>[] = [
    {
      key: "sku",
      header: "SKU",
      render: (r) => (
        <div className="flex flex-col">
          <code className="font-mono text-xs text-[var(--text-secondary)]">{r.sku_code}</code>
          {r.denomination && (
            <span className="text-[10px] text-[var(--text-tertiary)]">{r.denomination}</span>
          )}
        </div>
      ),
      className: "w-40",
      sortAccessor: (r) => r.sku_code,
    },
    {
      key: "brand",
      header: "Бренд / товар",
      render: (r) => (
        <div className="flex flex-col">
          <span>{r.brandName || "—"}</span>
          <span className="text-[10px] text-[var(--text-tertiary)]">{r.productSlug}</span>
        </div>
      ),
      className: "w-44",
      sortAccessor: (r) => r.brandName,
    },
    {
      key: "mode",
      header: "Режим",
      render: (r) => <ModeBadge mode={r.mode} />,
      className: "w-44",
    },
    {
      key: "supplier",
      header: "Поставщик",
      render: (r) =>
        r.supplier_slug ? (
          <code className="text-xs">{r.supplier_slug}</code>
        ) : (
          <span className="text-[var(--text-tertiary)]">—</span>
        ),
      className: "w-32",
    },
    {
      key: "updated",
      header: "Обновлено",
      render: (r) =>
        new Date(r.updated_at).toLocaleString("ru", {
          day: "2-digit",
          month: "2-digit",
          year: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }),
      className: "w-40",
      sortAccessor: (r) => r.updated_at,
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={(ev) => {
            ev.stopPropagation();
            if (window.confirm("Удалить правило? SKU вернётся в режим авто.")) {
              onDelete(r.sku_id);
            }
          }}
        >
          Удалить
        </Button>
      ),
      className: "w-24 text-right",
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-48 flex-1">
          <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
            Поиск
          </label>
          <Input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
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
              setModeFilter(e.target.value);
            }}
            containerClassName="w-44"
          >
            <option value="">Все режимы</option>
            {(Object.keys(MODE_LABELS) as SourcingMode[]).map((m) => (
              <option key={m} value={m}>
                {MODE_LABELS[m]}
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
              setSupplierFilter(e.target.value);
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

      <DataTable
        rows={filtered}
        columns={columns}
        rowKey={(r) => r.sku_id}
        loading={loading}
        empty={
          rules.length === 0
            ? "Явных правил нет — все SKU работают в режиме авто."
            : "Ничего не найдено по этому фильтру."
        }
      />
    </div>
  );
}

// Same tones `SourcingPage`'s single-SKU editor used before this table was
// split out — kept identical so a mode reads the same colour in both places.
const MODE_TONES: Record<SourcingMode, string> = {
  auto: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  force_inventory: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  force_supplier: "bg-[var(--info-soft)] text-[var(--info-fg)]",
  manual: "bg-[var(--warning-soft)] text-[var(--warning-fg)]",
};

function ModeBadge({ mode }: { mode: SourcingMode }) {
  return (
    <Badge tone={MODE_TONES[mode]} dot={mode !== "auto"}>
      {MODE_LABELS[mode]}
    </Badge>
  );
}
