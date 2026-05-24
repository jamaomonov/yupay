import { useQuery } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { Brand, Product } from "../types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

export function ProductsListPage() {
  const navigate = useNavigate();
  const productsQuery = useQuery<Product[]>({
    queryKey: qk.products(),
    queryFn: () => apiGet<Product[]>("/api/v1/admin/catalog/products"),
  });
  const brandsQuery = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });

  const brandsById = new Map(brandsQuery.data?.map((b) => [b.id, b]) ?? []);

  const columns: Column<Product>[] = [
    {
      key: "name",
      header: "Продукт",
      render: (p) => p.translations.find((t) => t.locale === "ru")?.name ?? p.slug,
    },
    {
      key: "brand",
      header: "Бренд",
      render: (p) => {
        const b = brandsById.get(p.brand_id);
        return b?.translations.find((t) => t.locale === "ru")?.name ?? b?.slug ?? p.brand_id;
      },
    },
    { key: "kind", header: "Тип", render: (p) => p.kind, className: "w-24" },
    {
      key: "fields",
      header: "Поля формы",
      render: (p) => `${p.required_fields.length}`,
      className: "w-28",
    },
    {
      key: "active",
      header: "Статус",
      render: (p) => (p.active ? "✓" : "—"),
      className: "w-16",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Продукты"
        description="UC, Royal Pass, Wallet, Gift Card. Каждый со своей формой ввода."
        actions={
          <Button onClick={() => navigate("/products/new")}>
            <Plus className="size-4" />
            Добавить продукт
          </Button>
        }
      />
      {productsQuery.isLoading && <Spinner label="Загрузка…" />}
      {productsQuery.data && (
        <DataTable
          rows={productsQuery.data}
          columns={columns}
          rowKey={(p) => p.id}
          onRowClick={(p) => navigate(`/products/${p.id}`)}
        />
      )}
    </div>
  );
}
