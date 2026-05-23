import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, Plus, Search, Trash2 } from "lucide-react";

import { Button, Input } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { ApiError, apiDelete, apiPatch, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import type { Brand, Product, Sku } from "../types";

interface GroupedProduct {
  product: Product;
  brand: Brand | undefined;
  skus: Sku[];
}

export function SkusListPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [onlyInactive, setOnlyInactive] = useState(false);

  const productsQuery = useQuery<Product[]>({
    queryKey: qk.products(),
    queryFn: () => apiGet<Product[]>("/api/v1/admin/catalog/products"),
  });
  const brandsQuery = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });
  const skusQuery = useQuery<Sku[]>({
    queryKey: qk.skus(),
    queryFn: () => apiGet<Sku[]>("/api/v1/admin/catalog/skus"),
  });

  const toggleActive = useMutation<Sku, ApiError, { sku: Sku; next: boolean }>({
    mutationFn: async ({ sku, next }) =>
      apiPatch<Sku>(`/api/v1/admin/catalog/skus/${sku.id}`, { active: next }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.skus() }),
  });

  const remove = useMutation<void, ApiError, Sku>({
    mutationFn: (sku) => apiDelete(`/api/v1/admin/catalog/skus/${sku.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.skus() }),
  });

  const groups = useMemo<GroupedProduct[]>(() => {
    const brandById = new Map((brandsQuery.data ?? []).map((b) => [b.id, b]));
    const bucket = new Map<string, GroupedProduct>();
    for (const product of productsQuery.data ?? []) {
      bucket.set(product.id, {
        product,
        brand: brandById.get(product.brand_id),
        skus: [],
      });
    }
    for (const sku of skusQuery.data ?? []) {
      const g = bucket.get(sku.product_id);
      if (g) g.skus.push(sku);
    }
    for (const g of bucket.values()) {
      g.skus.sort((a, b) => {
        if (a.sort_order !== b.sort_order) return a.sort_order - b.sort_order;
        const aPrice = Number.parseFloat(a.price_usd);
        const bPrice = Number.parseFloat(b.price_usd);
        if (!Number.isNaN(aPrice) && !Number.isNaN(bPrice) && aPrice !== bPrice) {
          return aPrice - bPrice;
        }
        return a.sku_code.localeCompare(b.sku_code);
      });
    }
    return [...bucket.values()].sort((a, b) => {
      // Show empty products first so they're impossible to miss.
      if (a.skus.length === 0 && b.skus.length > 0) return -1;
      if (b.skus.length === 0 && a.skus.length > 0) return 1;
      const aName = rname(a.brand) + " " + rname(a.product);
      const bName = rname(b.brand) + " " + rname(b.product);
      return aName.localeCompare(bName);
    });
  }, [productsQuery.data, brandsQuery.data, skusQuery.data]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return groups
      .map((g) => {
        if (q.length === 0 && !onlyInactive) return g;
        const matchesGroup =
          rname(g.brand).toLowerCase().includes(q) ||
          rname(g.product).toLowerCase().includes(q) ||
          g.product.slug.toLowerCase().includes(q);
        let skus = g.skus.filter((sku) => {
          if (onlyInactive && sku.active) return false;
          if (q.length === 0) return true;
          if (matchesGroup) return true;
          return (
            sku.sku_code.toLowerCase().includes(q) ||
            (sku.denomination ?? "").toLowerCase().includes(q) ||
            (sku.region ?? "").toLowerCase().includes(q)
          );
        });
        if (q.length > 0 && !matchesGroup && skus.length === 0) {
          return null;
        }
        if (onlyInactive && skus.length === 0) return null;
        // Even with q matching the group, hide if filter dropped everything.
        if (skus.length === 0 && !matchesGroup && !onlyInactive) return null;
        // Sort_order preserved by mapping
        return { ...g, skus };
      })
      .filter((g): g is GroupedProduct => g !== null);
  }, [groups, query, onlyInactive]);

  const totals = useMemo(() => {
    let totalSkus = 0;
    let inactive = 0;
    let emptyProducts = 0;
    for (const g of groups) {
      totalSkus += g.skus.length;
      inactive += g.skus.filter((s) => !s.active).length;
      if (g.skus.length === 0) emptyProducts++;
    }
    return {
      totalSkus,
      inactive,
      emptyProducts,
      products: groups.length,
    };
  }, [groups]);

  const isLoading =
    productsQuery.isLoading || brandsQuery.isLoading || skusQuery.isLoading;

  return (
    <div>
      <PageHeader
        title="SKU"
        description="Конкретные продаваемые позиции — номинал, регион, цена. Сгруппировано по продукту."
        actions={
          <Button onClick={() => navigate("/skus/new")}>
            <Plus className="size-4" />
            Новый SKU
          </Button>
        }
      />

      <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        <StatCard label="Продуктов" value={totals.products} />
        <StatCard label="SKU всего" value={totals.totalSkus} accent />
        <StatCard
          label="Неактивные"
          value={totals.inactive}
          tone={totals.inactive > 0 ? "warn" : "muted"}
        />
        <StatCard
          label="Без SKU"
          value={totals.emptyProducts}
          tone={totals.emptyProducts > 0 ? "warn" : "muted"}
        />
      </section>

      <section className="mb-5 flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[--text-secondary]" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Поиск по бренду, продукту, sku-code, региону…"
            className="pl-9"
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-[--text-secondary]">
          <input
            type="checkbox"
            checked={onlyInactive}
            onChange={(e) => setOnlyInactive(e.target.checked)}
            className="size-4"
          />
          только неактивные
        </label>
      </section>

      {isLoading && (
        <div className="rounded-lg border bg-[--bg-surface] p-10 text-center text-sm text-[--text-secondary]">
          Загрузка…
        </div>
      )}

      {!isLoading && filtered.length === 0 && (
        <div className="rounded-lg border bg-[--bg-surface] p-10 text-center">
          <p className="text-sm text-[--text-secondary]">
            {query.length > 0
              ? "Ничего не нашлось по этому запросу."
              : "SKU пока нет. Создай первый."}
          </p>
        </div>
      )}

      <div className="space-y-6">
        {filtered.map((g) => (
          <ProductGroup
            key={g.product.id}
            group={g}
            onToggle={(sku, next) => toggleActive.mutate({ sku, next })}
            onDelete={(sku) => {
              if (confirm(`Удалить SKU «${sku.sku_code}»?`)) remove.mutate(sku);
            }}
            isToggling={toggleActive.isPending}
            isDeleting={remove.isPending}
          />
        ))}
      </div>
    </div>
  );
}

function ProductGroup({
  group,
  onToggle,
  onDelete,
  isToggling,
  isDeleting,
}: {
  group: GroupedProduct;
  onToggle: (sku: Sku, next: boolean) => void;
  onDelete: (sku: Sku) => void;
  isToggling: boolean;
  isDeleting: boolean;
}) {
  const navigate = useNavigate();
  const productName = rname(group.product);
  const brandName = rname(group.brand);
  const isEmpty = group.skus.length === 0;

  return (
    <article className="overflow-hidden rounded-lg border bg-[--bg-surface]">
      <header
        className="flex flex-wrap items-baseline justify-between gap-3 border-b px-5 py-3"
        style={{
          background: isEmpty
            ? "color-mix(in oklab, var(--color-danger) 6%, var(--bg-surface))"
            : "var(--bg-muted)",
        }}
      >
        <div className="flex items-baseline gap-2">
          <span className="text-xs uppercase tracking-wide text-[--text-secondary]">
            {brandName || "—"}
          </span>
          <span className="text-[--text-secondary]">›</span>
          <h2 className="text-base font-semibold">
            <Link
              to={`/products/${group.product.id}`}
              className="hover:underline"
            >
              {productName || group.product.slug}
            </Link>
          </h2>
          <code className="ml-2 text-xs text-[--text-secondary]">
            {group.product.slug}
          </code>
          <span
            className={`ml-2 rounded-full px-2 py-0.5 text-xs ${
              group.skus.length > 0
                ? "bg-[--bg-surface] text-[--text-primary]"
                : "bg-[--color-danger]/10 text-[--danger]"
            }`}
          >
            {group.skus.length} SKU
          </span>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() =>
            navigate(`/skus/new?product_id=${group.product.id}`)
          }
        >
          <Plus className="size-4" />
          Добавить SKU
        </Button>
      </header>

      {isEmpty ? (
        <div className="p-8 text-center">
          <p className="text-sm text-[--text-secondary]">
            Ни одного SKU. Добавь хотя бы один — без него продукт не продаётся.
          </p>
        </div>
      ) : (
        <table className="w-full text-sm">
          <thead className="bg-[--bg-surface] text-xs uppercase text-[--text-secondary]">
            <tr>
              <th className="px-5 py-2 text-left font-medium">Номинал</th>
              <th className="px-3 py-2 text-left font-medium">Регион</th>
              <th className="px-3 py-2 text-left font-medium">SKU code</th>
              <th className="px-3 py-2 text-right font-medium">USD</th>
              <th className="px-3 py-2 text-left font-medium">Override</th>
              <th className="px-3 py-2 text-center font-medium">Активен</th>
              <th className="px-3 py-2 text-right font-medium">∑</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {group.skus.map((sku) => (
              <SkuRow
                key={sku.id}
                sku={sku}
                onToggle={(next) => onToggle(sku, next)}
                onEdit={() => navigate(`/skus/${sku.id}`)}
                onDelete={() => onDelete(sku)}
                disabled={isToggling || isDeleting}
              />
            ))}
          </tbody>
        </table>
      )}
    </article>
  );
}

function SkuRow({
  sku,
  onToggle,
  onEdit,
  onDelete,
  disabled,
}: {
  sku: Sku;
  onToggle: (next: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
  disabled: boolean;
}) {
  const usd = Number.parseFloat(sku.price_usd);
  return (
    <tr
      className={`group border-t transition-colors hover:bg-[--bg-muted]/60 ${
        sku.active ? "" : "opacity-60"
      }`}
    >
      <td className="px-5 py-2.5">
        <span className="font-medium">{sku.denomination ?? "—"}</span>
      </td>
      <td className="px-3 py-2.5">
        <span className="rounded-md bg-[--bg-muted] px-1.5 py-0.5 font-mono text-xs">
          {sku.region ?? "—"}
        </span>
      </td>
      <td className="px-3 py-2.5">
        <code className="text-xs">{sku.sku_code}</code>
      </td>
      <td className="px-3 py-2.5 text-right font-mono">
        {Number.isNaN(usd) ? sku.price_usd : `$${usd.toFixed(2)}`}
      </td>
      <td className="px-3 py-2.5">
        {sku.price_overrides.length === 0 ? (
          <span className="text-xs text-[--text-secondary]">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {sku.price_overrides.map((o) => (
              <span
                key={o.currency}
                className="rounded-md border border-[--border-default] bg-[--bg-surface] px-1.5 py-0.5 font-mono text-[10px]"
                title={`${o.price} ${o.currency}`}
              >
                {o.currency}
              </span>
            ))}
          </div>
        )}
      </td>
      <td className="px-3 py-2.5 text-center">
        <Toggle
          checked={sku.active}
          onChange={onToggle}
          disabled={disabled}
        />
      </td>
      <td className="px-3 py-2.5 text-right font-mono text-xs text-[--text-secondary]">
        {sku.sort_order}
      </td>
      <td className="px-3 py-2.5 text-right">
        <div
          className="flex justify-end gap-1 opacity-0 transition-opacity group-hover:opacity-100"
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onEdit}
            aria-label="Редактировать"
          >
            <Pencil className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onDelete}
            aria-label="Удалить"
            disabled={disabled}
          >
            <Trash2 className="size-4 text-[--danger]" />
          </Button>
        </div>
      </td>
    </tr>
  );
}

function Toggle({
  checked,
  onChange,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled: boolean;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      disabled={disabled}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
        checked
          ? "bg-[--accent]"
          : "bg-[--color-border]"
      } disabled:cursor-not-allowed disabled:opacity-50`}
    >
      <span
        className={`inline-block size-4 rounded-full bg-white shadow transition-transform ${
          checked ? "translate-x-4" : "translate-x-0.5"
        }`}
      />
    </button>
  );
}

function StatCard({
  label,
  value,
  accent,
  tone = "default",
}: {
  label: string;
  value: number;
  accent?: boolean;
  tone?: "default" | "warn" | "muted";
}) {
  const valueCls = accent
    ? "text-[--accent]"
    : tone === "warn"
      ? "text-[--danger]"
      : "text-[--text-primary]";
  return (
    <div className="rounded-lg border bg-[--bg-surface] p-4">
      <div className={`text-2xl font-semibold ${valueCls}`}>{value}</div>
      <div className="text-xs uppercase tracking-wide text-[--text-secondary]">
        {label}
      </div>
    </div>
  );
}

function rname<T extends { translations: { locale: string; name: string }[] }>(
  obj: T | undefined,
): string {
  if (!obj) return "";
  return obj.translations.find((t) => t.locale === "ru")?.name ?? "";
}
