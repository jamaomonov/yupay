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
import { Button } from "@yupay/ui";
import { useMemo, useState } from "react";

import { RulesTableFilters } from "./RulesTableFilters";
import { RulesTableGroups } from "./RulesTableGroups";

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
  /** `null` when the SKU, product or brand behind this rule is missing from
   *  the three catalog lists — every such rule shares that one `null` key
   *  and lands in the same "Без бренда" group below, same as before. A real
   *  brand id, by contrast, is only ever shared by rules that really are
   *  the same brand — unlike `brandName`, which two differently-id'd brands
   *  can share (the region rollout named two "Mobile Legends" and "Mobile
   *  Legends RU" today; nothing stops a future pair from matching
   *  exactly). Grouping on this instead of `brandName` is what keeps such a
   *  pair in two sections instead of one merged section with one count and
   *  one (colliding) React key. */
  brandId: string | null;
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
  // `supplierFilter` stays a bare `string`, not a narrower union: its
  // options come from `supplierOptions` below, itself derived at runtime
  // from whatever `rule.supplier_slug` values are actually present — the
  // field it filters (`SourcingRuleOut.supplier_slug`) is already typed
  // `string | null` at its source, so there is no closed union to narrow
  // to without inventing one the data model doesn't have.
  const [supplierFilter, setSupplierFilter] = useState("");
  const [modeFilter, setModeFilter] = useState<SourcingMode | "">("");

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
        brandId: brand?.id ?? null,
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

  // One group per brand *id*, each carrying its own rule count and label —
  // the filters above run first (on `enriched`, producing `filtered`), so a
  // group here only ever holds rows that already passed every active
  // filter, and a brand with nothing left after filtering simply has no
  // group at all rather than an empty one. Sorted alphabetically by label
  // for a stable order, same precedent as `supplierOptions` above.
  //
  // Keyed on `brandId`, not `brandName`: two brands can share a display
  // name (whole-branch review #3) — grouping on the name would merge them
  // into one section with one count and one React key. `null` (SKU/product/
  // brand missing from the catalog lists) still collapses into a single
  // "Без бренда" group, same as before — every such row genuinely shares
  // nothing else to group by either.
  const groups = useMemo<{ key: string; label: string; rows: EnrichedRule[] }[]>(() => {
    const byId = new Map<string | null, { label: string; rows: EnrichedRule[] }>();
    for (const r of filtered) {
      const label = r.brandName || "Без бренда";
      const group = byId.get(r.brandId);
      if (group) group.rows.push(r);
      else byId.set(r.brandId, { label, rows: [r] });
    }
    return [...byId.entries()]
      .sort(([, a], [, b]) => a.label.localeCompare(b.label))
      .map(([id, { label, rows }]) => ({ key: id ?? "__no_brand__", label, rows }));
  }, [filtered]);

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
      // Brand no longer repeats per row — it is now the group heading above
      // each table — so this column carries only the product, not "Бренд /
      // товар" as before.
      key: "product",
      header: "Товар",
      render: (r) => <span>{r.productSlug || "—"}</span>,
      className: "w-44",
      sortAccessor: (r) => r.productSlug,
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
      <RulesTableFilters
        search={search}
        onSearchChange={setSearch}
        modeFilter={modeFilter}
        onModeFilterChange={setModeFilter}
        modeLabels={MODE_LABELS}
        supplierFilter={supplierFilter}
        onSupplierFilterChange={setSupplierFilter}
        supplierOptions={supplierOptions}
      />

      {loading || filtered.length === 0 ? (
        <DataTable
          rows={[]}
          columns={columns}
          rowKey={(r) => r.sku_id}
          loading={loading}
          empty={
            rules.length === 0
              ? "Явных правил нет — все SKU работают в режиме авто."
              : "Ничего не найдено по этому фильтру."
          }
        />
      ) : (
        <RulesTableGroups groups={groups} columns={columns} rowKey={(r) => r.sku_id} />
      )}
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
