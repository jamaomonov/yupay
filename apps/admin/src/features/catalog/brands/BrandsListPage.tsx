import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";

import { Button } from "@yupay/ui";
import { Spinner } from "@/components/States";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { Brand } from "../types";

export function BrandsListPage() {
  const navigate = useNavigate();
  const q = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });

  const columns: Column<Brand>[] = [
    {
      key: "name",
      header: "Бренд",
      render: (b) => (
        <div className="flex items-center gap-2">
          {b.accent_color && (
            <span
              className="inline-block size-3 rounded-full"
              style={{ background: b.accent_color }}
            />
          )}
          <span>{b.translations.find((t) => t.locale === "ru")?.name ?? b.slug}</span>
        </div>
      ),
    },
    { key: "slug", header: "Slug", render: (b) => <code className="text-xs">{b.slug}</code> },
    { key: "sort", header: "Порядок", render: (b) => b.sort_order, className: "w-24" },
    {
      key: "active",
      header: "Статус",
      render: (b) => (b.active ? "✓" : "—"),
      className: "w-16",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Бренды"
        description="Игры, сервисы, подписки. Один бренд → много продуктов."
        actions={
          <Button onClick={() => navigate("/brands/new")}>
            <Plus className="size-4" />
            Добавить бренд
          </Button>
        }
      />
      {q.isLoading && <Spinner label="Загрузка…" />}
      {q.isError && <p className="text-sm text-[--danger]">Ошибка загрузки.</p>}
      {q.data && (
        <DataTable
          rows={q.data}
          columns={columns}
          rowKey={(b) => b.id}
          onRowClick={(b) => navigate(`/brands/${b.id}`)}
        />
      )}
      {q.data && q.data.length === 0 && (
        <p className="mt-4 text-sm text-[--text-secondary]">
          Ничего нет. <Link to="/brands/new" className="underline">Создать первый</Link>?
        </p>
      )}
    </div>
  );
}
