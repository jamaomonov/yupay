import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input, Select } from "@yupay/ui";
import { Pencil, Plus, RefreshCcw, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";

import type { Brand, Product, Sku } from "../types";

import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { StatCard } from "@/components/StatCard";
import { Thumb } from "@/components/Thumb";
import { useToast } from "@/components/Toast";
import { type ApiError, apiDelete, apiPatch, apiGet, apiPost } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { qk } from "@/lib/queryKeys";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

/** Page size. The server orders by product then SKU, so a page holds whole
 *  products and the grouping below never splits one across two pages. */
const PAGE_SIZE = 100;

interface GroupedProduct {
  product: Product;
  brand: Brand | undefined;
  skus: Sku[];
}

/** `GET /admin/catalog/skus` — paged since the catalogue passed 6000 SKUs. */
interface SkuPageOut {
  items: Sku[];
  total: number;
}

interface BulkUzsPriceOut {
  rate: string;
  fx_snapshot_id: string | null;
  updated_total: number;
  skipped_variable_amount: number;
}

// Stable fallbacks, so a loading query does not hand the memos below a fresh
// `[]` on every render and recompute them for nothing.
const NO_PRODUCTS: Product[] = [];
const NO_BRANDS: Brand[] = [];
const NO_SKUS: Sku[] = [];

function parseOffset(raw: string | null): number {
  const n = Number(raw ?? "0");
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

export function SkusListPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const toast = useToast();
  // In the URL, not in component state. Editing a SKU navigates away and back,
  // and state died with the unmount — so an operator working through search
  // results retyped the query after every single edit. The address bar already
  // survives that trip, and it makes a filtered list something you can send to
  // someone.
  const location = useLocation();
  const [params, setParams] = useSearchParams();
  const query = params.get("q") ?? "";
  const onlyInactive = params.get("inactive") === "1";
  const brandId = params.get("brand") ?? "";
  const productId = params.get("product") ?? "";
  const offset = parseOffset(params.get("offset"));
  const patchParams = useCallback(
    (next: Record<string, string | null>) => {
      setParams(
        (prev) => {
          const merged = new URLSearchParams(prev);
          for (const [k, v] of Object.entries(next)) {
            if (v === null || v === "") merged.delete(k);
            else merged.set(k, v);
          }
          return merged;
        },
        // Replace, so a search does not bury the previous page under history
        // entries the back button then has to walk through character by character.
        { replace: true },
      );
    },
    [setParams],
  );

  // The field is local state so typing stays instant; the URL — and with it
  // the request — only sees the value once it has been stable for 300 ms.
  const [draft, setDraft] = useState(query);
  const debouncedDraft = useDebouncedValue(draft, 300);
  useEffect(() => {
    if (debouncedDraft === query) return;
    // A new search means a new result set; an offset into the old one is
    // meaningless against it.
    patchParams({ q: debouncedDraft, offset: null });
  }, [debouncedDraft, query, patchParams]);

  const productsQuery = useQuery<Product[]>({
    queryKey: qk.products(),
    queryFn: () => apiGet<Product[]>("/api/v1/admin/catalog/products"),
  });
  const brandsQuery = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });
  const skusQuery = useQuery<SkuPageOut>({
    queryKey: qk.skusPage({
      q: query || null,
      brandId: brandId || null,
      productId: productId || null,
      active: onlyInactive ? false : null,
      offset,
    }),
    queryFn: () => {
      const sp = new URLSearchParams();
      if (query) sp.set("q", query);
      if (brandId) sp.set("brand_id", brandId);
      if (productId) sp.set("product_id", productId);
      if (onlyInactive) sp.set("active", "false");
      sp.set("limit", String(PAGE_SIZE));
      sp.set("offset", String(offset));
      return apiGet<SkuPageOut>(`/api/v1/admin/catalog/skus?${sp.toString()}`);
    },
  });

  const invalidatePages = () => qc.invalidateQueries({ queryKey: qk.skusPages() });

  const toggleActive = useMutation<Sku, ApiError, { sku: Sku; next: boolean }>({
    mutationFn: async ({ sku, next }) =>
      apiPatch<Sku>(`/api/v1/admin/catalog/skus/${sku.id}`, { active: next }),
    onSuccess: invalidatePages,
  });

  const remove = useMutation<void, ApiError, Sku>({
    mutationFn: (sku) => apiDelete(`/api/v1/admin/catalog/skus/${sku.id}`),
    onSuccess: invalidatePages,
  });

  const bulkSetUzs = useMutation<BulkUzsPriceOut, ApiError>({
    mutationFn: () =>
      apiPost<BulkUzsPriceOut>("/api/v1/admin/catalog/skus/bulk-set-uzs-prices", {}),
    onSuccess: (data) => {
      const rate = Number.parseFloat(data.rate).toLocaleString("ru-RU", {
        maximumFractionDigits: 2,
      });
      toast.success(
        `UZS-цены пересчитаны: ${data.updated_total.toString()} SKU @ 1 USDT = ${rate} UZS. Пропущено Steam-позиций с произвольной суммой: ${data.skipped_variable_amount.toString()}.`,
      );
      void invalidatePages();
    },
    onError: () => {
      toast.error("Не удалось пересчитать UZS-цены. Проверь, что FX-провайдер отвечает.");
    },
  });

  const products = productsQuery.data ?? NO_PRODUCTS;
  const brands = brandsQuery.data ?? NO_BRANDS;
  const items = skusQuery.data?.items ?? NO_SKUS;
  const total = skusQuery.data?.total ?? 0;

  const sortedBrands = useMemo(
    () => [...brands].sort((a, b) => rname(a).localeCompare(rname(b))),
    [brands],
  );
  const productOptions = useMemo(() => {
    const scoped = brandId ? products.filter((p) => p.brand_id === brandId) : products;
    return [...scoped].sort((a, b) => rname(a).localeCompare(rname(b)));
  }, [products, brandId]);

  const groups = useMemo<GroupedProduct[]>(() => {
    const brandById = new Map(brands.map((b) => [b.id, b]));
    const productById = new Map(products.map((p) => [p.id, p]));
    // Server order: product sort_order/slug, then SKU sort_order/code. A Map
    // keeps insertion order, so the groups come out in the same sequence.
    const bucket = new Map<string, GroupedProduct>();
    for (const sku of items) {
      let g = bucket.get(sku.product_id);
      if (!g) {
        const product = productById.get(sku.product_id);
        if (!product) continue;
        g = { product, brand: brandById.get(product.brand_id), skus: [] };
        bucket.set(sku.product_id, g);
      }
      g.skus.push(sku);
    }
    // Products with no SKU at all cannot be computed from one page of 6000
    // SKUs. Under a brand filter they can — as long as this page *is* the
    // brand's whole unfiltered result set, so "absent from the page" really
    // does mean "has no SKU" and not "is on page two" or "was filtered out".
    const wholeBrand =
      brandId !== "" && query === "" && !onlyInactive && offset === 0 && total <= PAGE_SIZE;
    const empties: GroupedProduct[] = wholeBrand
      ? products
          .filter(
            (p) =>
              p.brand_id === brandId &&
              (productId === "" || p.id === productId) &&
              !bucket.has(p.id),
          )
          .map((p) => ({ product: p, brand: brandById.get(p.brand_id), skus: [] }))
      : [];
    // Empty products first so they're impossible to miss.
    return [...empties, ...bucket.values()];
  }, [brands, products, items, brandId, productId, query, onlyInactive, offset, total]);

  const hasFilter = query !== "" || onlyInactive || brandId !== "" || productId !== "";
  const isLoading = productsQuery.isLoading || brandsQuery.isLoading || skusQuery.isLoading;

  return (
    <div>
      <PageHeader
        title="SKU"
        description="Конкретные продаваемые позиции — номинал, регион, цена. Сгруппировано по продукту."
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => {
                if (
                  confirm(
                    "Зафиксировать UZS-цены всех активных SKU как price_usd × текущий курс? Старые UZS-override'ы будут перезаписаны; дальше они двигаются вместе с ценой в USD.",
                  )
                ) {
                  bulkSetUzs.mutate();
                }
              }}
              disabled={bulkSetUzs.isPending}
              title="UZS price = price_usd (цена продажи) × текущий курс USDT→UZS"
            >
              <RefreshCcw className={`size-4 ${bulkSetUzs.isPending ? "animate-spin" : ""}`} />
              {bulkSetUzs.isPending ? "Считаем…" : "Обновить UZS-цены"}
            </Button>
            <Button onClick={() => navigate("/skus/new")}>
              <Plus className="size-4" />
              Новый SKU
            </Button>
          </>
        }
      />

      <section className="mb-5 grid grid-cols-2 gap-3">
        <StatCard label="Найдено SKU" value={total} accent />
        <StatCard label="Продуктов (всего)" value={products.length} />
      </section>

      <section className="mb-5 flex flex-wrap items-center gap-3">
        <div className="relative min-w-64 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[var(--text-secondary)]" />
          <Input
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
            }}
            placeholder="Поиск по бренду, продукту, sku-code, номиналу…"
            className="pl-9"
          />
        </div>
        <Select
          aria-label="Бренд"
          value={brandId}
          onChange={(e) => {
            // The product list is scoped to the brand, so a product picked
            // under the old brand has nothing to do with the new one.
            patchParams({ brand: e.target.value, product: null, offset: null });
          }}
          containerClassName="w-auto"
        >
          <option value="">Бренд: все</option>
          {sortedBrands.map((b) => (
            <option key={b.id} value={b.id}>
              {rname(b) || b.slug}
            </option>
          ))}
        </Select>
        <Select
          aria-label="Продукт"
          value={productId}
          onChange={(e) => {
            patchParams({ product: e.target.value, offset: null });
          }}
          containerClassName="w-auto"
        >
          <option value="">Продукт: все</option>
          {productOptions.map((p) => (
            <option key={p.id} value={p.id}>
              {rname(p) || p.slug}
            </option>
          ))}
        </Select>
        <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
          <input
            type="checkbox"
            checked={onlyInactive}
            onChange={(e) => {
              patchParams({ inactive: e.target.checked ? "1" : null, offset: null });
            }}
            className="size-4"
          />
          только неактивные
        </label>
      </section>

      {isLoading && (
        <div className="rounded-lg border bg-[var(--bg-surface)] p-10 text-center text-sm text-[var(--text-secondary)] shadow-[var(--shadow-sm)]">
          Загрузка…
        </div>
      )}

      {!isLoading && groups.length === 0 && (
        <div className="rounded-lg border bg-[var(--bg-surface)] p-10 text-center shadow-[var(--shadow-sm)]">
          <p className="text-sm text-[var(--text-secondary)]">
            {hasFilter ? "Ничего не нашлось по этому запросу." : "SKU пока нет. Создай первый."}
          </p>
        </div>
      )}

      <div className="space-y-6">
        {groups.map((g) => (
          <ProductGroup
            key={g.product.id}
            group={g}
            onToggle={(sku, next) => {
              toggleActive.mutate({ sku, next });
            }}
            onDelete={(sku) => {
              if (confirm(`Удалить SKU «${sku.sku_code}»?`)) remove.mutate(sku);
            }}
            // Carried into the editor so its Cancel/Save can come back to the
            // list the operator was actually looking at, not to a bare one.
            listSearch={location.search}
            isToggling={toggleActive.isPending}
            isDeleting={remove.isPending}
          />
        ))}
      </div>

      {skusQuery.data && (
        <Pagination
          total={total}
          limit={PAGE_SIZE}
          offset={offset}
          onPageChange={(next) => {
            patchParams({ offset: next > 0 ? String(next) : null });
          }}
        />
      )}
    </div>
  );
}

function ProductGroup({
  group,
  onToggle,
  onDelete,
  listSearch,
  isToggling,
  isDeleting,
}: {
  group: GroupedProduct;
  onToggle: (sku: Sku, next: boolean) => void;
  onDelete: (sku: Sku) => void;
  listSearch: string;
  isToggling: boolean;
  isDeleting: boolean;
}) {
  const navigate = useNavigate();
  const productName = rname(group.product);
  const brandName = rname(group.brand);
  const isEmpty = group.skus.length === 0;

  return (
    <article className="overflow-hidden rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header
        className="flex flex-wrap items-baseline justify-between gap-3 border-b px-5 py-3"
        style={{
          background: isEmpty
            ? "color-mix(in oklab, var(--color-danger) 6%, var(--bg-surface))"
            : "var(--bg-muted)",
        }}
      >
        <div className="flex items-center gap-2">
          <Thumb src={group.brand?.logo_url} name={brandName || group.product.slug} />
          <span className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">
            {brandName || "—"}
          </span>
          <span className="text-[var(--text-secondary)]">›</span>
          <h2 className="text-base font-semibold">
            <Link to={`/products/${group.product.id}`} className="hover:underline">
              {productName || group.product.slug}
            </Link>
          </h2>
          <code className="ml-2 text-xs text-[var(--text-secondary)]">{group.product.slug}</code>
          <span
            className={`ml-2 rounded-full px-2 py-0.5 text-xs ${
              group.skus.length > 0
                ? "bg-[var(--bg-surface)] text-[var(--text-primary)]"
                : "bg-[var(--color-danger)]/10 text-[var(--danger)]"
            }`}
          >
            {group.skus.length} SKU
          </span>
        </div>
        <Button
          variant="secondary"
          size="sm"
          onClick={() =>
            navigate(`/skus/new?product_id=${group.product.id}`, { state: { listSearch } })
          }
        >
          <Plus className="size-4" />
          Добавить SKU
        </Button>
      </header>

      {isEmpty ? (
        <div className="p-8 text-center">
          <p className="text-sm text-[var(--text-secondary)]">
            Ни одного SKU. Добавь хотя бы один — без него продукт не продаётся.
          </p>
        </div>
      ) : (
        // Nine columns. `w-full` alone lets the browser squeeze them all into
        // a phone's width instead of overflowing, so `overflow-x-auto` on the
        // wrapper never had anything to scroll and the right-hand columns were
        // crushed to nothing. A minimum width is what turns compression into
        // a scroll.
        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] text-sm">
            <thead className="bg-[var(--bg-surface)] text-xs uppercase text-[var(--text-secondary)]">
              <tr>
                <th className="px-5 py-2 text-left font-medium">Номинал</th>
                <th className="px-3 py-2 text-left font-medium">Регион</th>
                <th className="px-3 py-2 text-left font-medium">SKU code</th>
                <th className="px-3 py-2 text-right font-medium">USD</th>
                <th className="px-3 py-2 text-right font-medium">Cost ₮</th>
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
                  onToggle={(next) => {
                    onToggle(sku, next);
                  }}
                  onEdit={() => navigate(`/skus/${sku.id}`, { state: { listSearch } })}
                  onDelete={() => {
                    onDelete(sku);
                  }}
                  disabled={isToggling || isDeleting}
                />
              ))}
            </tbody>
          </table>
        </div>
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
      className={`hover:bg-[var(--bg-muted)]/60 group border-t transition-colors ${
        sku.active ? "" : "opacity-60"
      }`}
    >
      <td className="px-5 py-2.5">
        <span className="flex items-center gap-2">
          <Thumb src={sku.image_url} name={sku.denomination ?? sku.sku_code} />
          <span className="font-medium">{sku.denomination ?? "—"}</span>
        </span>
      </td>
      <td className="px-3 py-2.5">
        <span className="rounded-md bg-[var(--bg-muted)] px-1.5 py-0.5 font-mono text-xs">
          {sku.region ?? "—"}
        </span>
      </td>
      <td className="px-3 py-2.5">
        <code className="text-xs">{sku.sku_code}</code>
      </td>
      <td className="px-3 py-2.5 text-right font-mono">
        {Number.isNaN(usd) ? sku.price_usd : `$${usd.toFixed(2)}`}
      </td>
      <td className="px-3 py-2.5 text-right font-mono text-xs">
        {sku.cost_usdt ? (
          (Number.parseFloat(sku.cost_usdt) || 0).toFixed(2)
        ) : (
          <span className="text-[var(--text-secondary)]">—</span>
        )}
      </td>
      <td className="px-3 py-2.5">
        {sku.price_overrides.length === 0 ? (
          <span className="text-xs text-[var(--text-secondary)]">—</span>
        ) : (
          <div className="flex flex-wrap gap-1">
            {sku.price_overrides.map((o) => (
              <span
                key={o.currency}
                className="rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-1.5 py-0.5 font-mono text-[10px]"
                title={formatMoney(o.price, o.currency)}
              >
                {o.currency}
              </span>
            ))}
          </div>
        )}
      </td>
      <td className="px-3 py-2.5 text-center">
        <Toggle checked={sku.active} onChange={onToggle} disabled={disabled} />
      </td>
      <td className="px-3 py-2.5 text-right font-mono text-xs text-[var(--text-secondary)]">
        {sku.sort_order}
      </td>
      <td className="px-3 py-2.5 text-right">
        <div
          // Visible by default, hover-revealed only from `md` up. The
          // reveal was unconditional, and a touch device has no hover — so
          // «Редактировать» was permanently invisible on every phone and the
          // row carries no click of its own, which made the edit page
          // unreachable rather than merely awkward. `group-focus-within`
          // brings it back for a keyboard too, which had the same problem
          // and nobody had noticed.
          className="flex justify-end gap-1 opacity-100 transition-opacity md:opacity-0 md:group-focus-within:opacity-100 md:group-hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
          }}
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
            <Trash2 className="size-4 text-[var(--danger)]" />
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
      onClick={() => {
        onChange(!checked);
      }}
      disabled={disabled}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
        checked ? "bg-[var(--accent)]" : "bg-[var(--color-border)]"
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

function rname<T extends { translations: { locale: string; name: string }[] }>(
  obj: T | undefined,
): string {
  if (!obj) return "";
  return obj.translations.find((t) => t.locale === "ru")?.name ?? "";
}
