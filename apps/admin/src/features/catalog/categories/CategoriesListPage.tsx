import { useQuery } from "@tanstack/react-query";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { Category } from "../types";

export function CategoriesListPage() {
  const q = useQuery<Category[]>({
    queryKey: qk.categories(),
    queryFn: () => apiGet<Category[]>("/api/v1/admin/catalog/categories"),
  });

  const columns: Column<Category>[] = [
    {
      key: "slug",
      header: "Slug",
      render: (c) => <code className="text-xs">{c.slug}</code>,
    },
    {
      key: "name",
      header: "Название (ru)",
      render: (c) => c.translations.find((t) => t.locale === "ru")?.name ?? "—",
    },
    { key: "sort", header: "Порядок", render: (c) => c.sort_order, className: "w-24" },
    {
      key: "active",
      header: "Статус",
      render: (c) => (c.active ? "✓ Активна" : "— Скрыта"),
      className: "w-32",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Категории"
        description="Верхний уровень навигации (плоский список)."
      />
      {q.isLoading && <p className="text-sm text-[--color-muted]">Загрузка…</p>}
      {q.isError && <p className="text-sm text-[--color-danger]">Ошибка загрузки.</p>}
      {q.data && <DataTable rows={q.data} columns={columns} rowKey={(c) => c.id} />}
    </div>
  );
}
