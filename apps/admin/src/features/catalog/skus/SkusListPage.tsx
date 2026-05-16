import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { Product, Sku } from "../types";

export function SkusListPage() {
  const [productId, setProductId] = useState<string>("");

  const productsQuery = useQuery<Product[]>({
    queryKey: qk.products(),
    queryFn: () => apiGet<Product[]>("/api/v1/admin/catalog/products"),
  });

  const skusQuery = useQuery<Sku[]>({
    queryKey: qk.skus({ productId: productId || null }),
    queryFn: () =>
      apiGet<Sku[]>(
        productId
          ? `/api/v1/admin/catalog/skus?product_id=${encodeURIComponent(productId)}`
          : "/api/v1/admin/catalog/skus",
      ),
  });

  const columns: Column<Sku>[] = [
    {
      key: "sku",
      header: "SKU code",
      render: (s) => <code className="text-xs">{s.sku_code}</code>,
    },
    { key: "denom", header: "Номинал", render: (s) => s.denomination ?? "—" },
    { key: "region", header: "Регион", render: (s) => s.region ?? "—", className: "w-20" },
    {
      key: "price",
      header: "USD",
      render: (s) => Number.parseFloat(s.price_usd).toFixed(2),
      className: "w-20",
    },
    {
      key: "overrides",
      header: "Override",
      render: (s) =>
        s.price_overrides.length === 0
          ? "—"
          : s.price_overrides.map((o) => o.currency).join(", "),
    },
    {
      key: "active",
      header: "Статус",
      render: (s) => (s.active ? "✓" : "—"),
      className: "w-16",
    },
  ];

  return (
    <div>
      <PageHeader
        title="SKU"
        description="Конкретные продаваемые позиции с ценой и регионом."
      />
      <div className="mb-4">
        <label className="text-xs font-medium uppercase text-[--color-muted]">
          Продукт
        </label>
        <select
          value={productId}
          onChange={(e) => setProductId(e.target.value)}
          className="ml-2 h-10 rounded-md border border-[--color-border] bg-[--color-bg] px-3 text-sm"
        >
          <option value="">— Все —</option>
          {productsQuery.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.translations.find((t) => t.locale === "ru")?.name ?? p.slug}
            </option>
          ))}
        </select>
      </div>
      {skusQuery.data && (
        <DataTable rows={skusQuery.data} columns={columns} rowKey={(s) => s.id} />
      )}
    </div>
  );
}
