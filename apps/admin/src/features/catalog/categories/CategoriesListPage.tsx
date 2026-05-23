import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { Pencil, Plus, Trash2 } from "lucide-react";

import { Button } from "@yupay/ui";
import { Spinner } from "@/components/States";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { ApiError, apiDelete, apiGet, apiPatch } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { Category } from "../types";

export function CategoriesListPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();

  const q = useQuery<Category[]>({
    queryKey: qk.categories(),
    queryFn: () => apiGet<Category[]>("/api/v1/admin/catalog/categories"),
  });

  const toggleActive = useMutation<
    Category,
    ApiError,
    { cat: Category; next: boolean }
  >({
    mutationFn: ({ cat, next }) =>
      apiPatch<Category>(`/api/v1/admin/catalog/categories/${cat.id}`, {
        active: next,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.categories() }),
  });

  const remove = useMutation<void, ApiError, Category>({
    mutationFn: (cat) => apiDelete(`/api/v1/admin/catalog/categories/${cat.id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.categories() }),
  });

  const sorted = (q.data ?? [])
    .slice()
    .sort((a, b) =>
      a.sort_order !== b.sort_order
        ? a.sort_order - b.sort_order
        : a.slug.localeCompare(b.slug),
    );

  const columns: Column<Category>[] = [
    {
      key: "slug",
      header: "Slug",
      render: (c) => <code className="text-xs">{c.slug}</code>,
      className: "w-40",
    },
    {
      key: "name",
      header: "Название (ru)",
      render: (c) => {
        const ru = c.translations.find((t) => t.locale === "ru")?.name ?? "—";
        return <span className="font-medium">{ru}</span>;
      },
    },
    {
      key: "icon",
      header: "Иконка",
      render: (c) =>
        c.icon ? <code className="text-xs">{c.icon}</code> : "—",
      className: "w-28",
    },
    {
      key: "sort",
      header: "Порядок",
      render: (c) => <span className="font-mono text-xs">{c.sort_order}</span>,
      className: "w-20 text-right",
    },
    {
      key: "active",
      header: "Активна",
      render: (c) => (
        <Toggle
          checked={c.active}
          onChange={(next) => toggleActive.mutate({ cat: c, next })}
          disabled={toggleActive.isPending}
        />
      ),
      className: "w-24 text-center",
    },
    {
      key: "actions",
      header: "",
      render: (c) => (
        <div
          className="flex justify-end gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/categories/${c.id}`)}
            aria-label="Редактировать"
          >
            <Pencil className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              if (
                confirm(
                  `Удалить категорию «${
                    c.translations.find((t) => t.locale === "ru")?.name ?? c.slug
                  }»?`,
                )
              ) {
                remove.mutate(c);
              }
            }}
            aria-label="Удалить"
            disabled={remove.isPending}
          >
            <Trash2 className="size-4 text-[--danger]" />
          </Button>
        </div>
      ),
      className: "w-28 text-right",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Категории"
        description="Верхний уровень навигации витрины — Игры, Подписки, Подарочные карты."
        actions={
          <Button onClick={() => navigate("/categories/new")}>
            <Plus className="size-4" />
            Новая категория
          </Button>
        }
      />
      {q.isLoading && <Spinner label="Загрузка…" />}
      {q.isError && <p className="text-sm text-[--danger]">Ошибка загрузки.</p>}
      {q.data && (
        <DataTable
          rows={sorted}
          columns={columns}
          rowKey={(c) => c.id}
          empty="Нет ни одной категории. Создай первую — без неё бренды некуда привязать."
          onRowClick={(c) => navigate(`/categories/${c.id}`)}
        />
      )}
    </div>
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
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      disabled={disabled}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
        checked ? "bg-[--accent]" : "bg-[--color-border]"
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
