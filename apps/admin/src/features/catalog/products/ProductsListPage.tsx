import { useQuery } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { Plus } from "lucide-react";
import { useNavigate } from "react-router-dom";

import type { Brand, Product } from "../types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SearchBox } from "@/components/SearchBox";
import { Thumb } from "@/components/Thumb";
import { Spinner } from "@/components/States";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { matchesText } from "@/lib/textSearch";
import { useSearchParamsState } from "@/lib/useSearchParamsState";

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
  const [query, setQuery] = useSearchParamsState("q", "");
  // A product is found by its own names and slug and by its brand's, so «pubg» lists every
  // PUBG product even where the product name says only «UC».
  const filtered = productsQuery.data?.filter((p) => {
    const b = brandsById.get(p.brand_id);
    return matchesText(query, [
      p.slug,
      ...p.translations.map((t) => t.name),
      b?.slug,
      ...(b?.translations.map((t) => t.name) ?? []),
    ]);
  });

  const columns: Column<Product>[] = [
    {
      key: "name",
      header: "Продукт",
      render: (p) => {
        const name = p.translations.find((t) => t.locale === "ru")?.name ?? p.slug;
        return (
          <span className="flex items-center gap-2">
            <Thumb src={p.image_url} name={name} />
            <span>{name}</span>
          </span>
        );
      },
    },
    {
      key: "brand",
      header: "Бренд",
      render: (p) => {
        const b = brandsById.get(p.brand_id);
        const name = b?.translations.find((t) => t.locale === "ru")?.name ?? b?.slug ?? p.brand_id;
        return (
          <span className="flex items-center gap-2">
            <Thumb src={b?.logo_url} name={name} />
            <span>{name}</span>
          </span>
        );
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
      <section className="mb-4 flex flex-wrap items-center gap-3">
        <SearchBox
          value={query}
          onChange={setQuery}
          placeholder="Поиск по продукту, бренду или slug…"
        />
        {query.trim() !== "" && filtered && productsQuery.data && (
          <span className="text-sm text-[var(--text-secondary)]">
            {filtered.length} из {productsQuery.data.length}
          </span>
        )}
      </section>
      {productsQuery.isLoading && <Spinner label="Загрузка…" />}
      {filtered && (
        <DataTable
          rows={filtered}
          columns={columns}
          rowKey={(p) => p.id}
          onRowClick={(p) => navigate(`/products/${p.id}`)}
        />
      )}
      {query.trim() !== "" && filtered?.length === 0 && (
        <p className="mt-4 text-sm text-[var(--text-secondary)]">Ничего не найдено.</p>
      )}
    </div>
  );
}
