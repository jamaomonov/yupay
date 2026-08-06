/** SKU↔supplier mapping list — the table operators live in when wiring
 *  new SKUs through to G2B (or any future supplier).
 *
 *  The filter is URL-driven (``?supplier=g2b``) so deep-links from the
 *  detail page land directly on the right slice. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { Plus, Trash2 } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";

import { SUPPLIER_LABELS, type SupplierMapping, type SupplierMappingListOut } from "./types";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";
import { ApiError, apiDelete, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

export function MappingsPage() {
  const [params, setParams] = useSearchParams();
  const supplier = params.get("supplier");
  const toast = useToast();
  const qc = useQueryClient();

  const listing = useQuery<SupplierMappingListOut>({
    queryKey: qk.integrationMappings({ supplierSlug: supplier }),
    queryFn: () =>
      apiGet<SupplierMappingListOut>(
        `/api/v1/admin/integrations/mappings${supplier ? `?supplier_slug=${supplier}` : ""}`,
      ),
  });

  const remove = useMutation<void, ApiError, { sku_id: string; supplier_slug: string }>({
    mutationFn: ({ sku_id, supplier_slug }) =>
      apiDelete(`/api/v1/admin/integrations/mappings/${sku_id}/${supplier_slug}`),
    onSuccess: () => {
      toast.success("Маппинг удалён");
      void qc.invalidateQueries({ queryKey: qk.integrationMappings({ supplierSlug: supplier }) });
    },
    onError: (err) => {
      toast.error(`Не удалось удалить: ${formatError(err)}`);
    },
  });

  const columns: Column<SupplierMapping>[] = [
    {
      key: "sku",
      header: "SKU",
      render: (r) => (
        <Link
          to={`/skus/${r.sku_id}`}
          className="font-mono text-xs underline-offset-2 hover:underline"
        >
          {r.sku_code}
        </Link>
      ),
      className: "w-40",
    },
    {
      key: "supplier",
      header: "Поставщик",
      render: (r) => (
        <Link
          to={`/integrations/${r.supplier_slug}`}
          className="underline-offset-2 hover:underline"
        >
          {SUPPLIER_LABELS[r.supplier_slug as keyof typeof SUPPLIER_LABELS] ?? r.supplier_slug}
        </Link>
      ),
    },
    {
      key: "kind",
      header: "Тип",
      render: (r) => (
        <span className="rounded-md bg-[var(--bg-muted)] px-2 py-0.5 font-mono text-xs">
          {r.kind}
        </span>
      ),
    },
    {
      key: "external",
      header: "Внешний ID",
      render: (r) => (
        <div className="flex flex-col">
          <code className="font-mono text-xs">{r.external_product_id}</code>
          {r.external_variant_id && (
            <code className="text-[10px] text-[var(--text-tertiary)]">{r.external_variant_id}</code>
          )}
        </div>
      ),
    },
    {
      key: "quantity",
      header: "К-во",
      render: (r) => <span className="font-mono text-sm">×{r.quantity.toString()}</span>,
      className: "w-20 text-right",
    },
    {
      key: "active",
      header: "Активен",
      render: (r) => (
        <span
          className={`rounded-full px-2 py-0.5 text-xs ${
            r.is_active
              ? "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]"
              : "bg-[var(--bg-muted)] text-[var(--text-secondary)]"
          }`}
        >
          {r.is_active ? "да" : "нет"}
        </span>
      ),
      className: "w-24",
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex items-center justify-end gap-2">
          <Link
            to={`/integrations/mappings/${r.supplier_slug}/${r.sku_id}/edit`}
            className="text-xs underline-offset-2 hover:underline"
          >
            Изменить
          </Link>
          <button
            type="button"
            onClick={() => {
              if (window.confirm("Удалить маппинг? Заказы на этот SKU через поставщика упадут.")) {
                remove.mutate({ sku_id: r.sku_id, supplier_slug: r.supplier_slug });
              }
            }}
            className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--danger)]"
            aria-label="Удалить маппинг"
          >
            <Trash2 className="size-4" />
          </button>
        </div>
      ),
      className: "w-32 text-right",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Маппинги SKU"
        description="Связь нашего SKU с продуктом / игрой у поставщика. Используется адаптером во время fulfilment."
        breadcrumbs={[{ label: "Интеграции", to: "/integrations" }, { label: "Маппинги" }]}
        actions={
          <Link
            to="/integrations/mappings/new"
            className="inline-flex h-8 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-[var(--text-on-accent)] hover:bg-[var(--accent-hover)]"
          >
            <Plus className="size-4" />
            Создать
          </Link>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-xs text-[var(--text-secondary)]">Поставщик:</span>
        <FilterChip
          label="Все"
          active={!supplier}
          onClick={() => {
            params.delete("supplier");
            setParams(params, { replace: true });
          }}
        />
        {Object.entries(SUPPLIER_LABELS).map(([slug, label]) => (
          <FilterChip
            key={slug}
            label={label}
            active={supplier === slug}
            onClick={() => {
              params.set("supplier", slug);
              setParams(params, { replace: true });
            }}
          />
        ))}
        <span className="ml-auto text-xs text-[var(--text-tertiary)]">
          Всего: {(listing.data?.items.length ?? 0).toString()}
        </span>
      </div>

      <DataTable
        rows={listing.data?.items ?? []}
        columns={columns}
        rowKey={(r) => `${r.sku_id}-${r.supplier_slug}`}
        loading={listing.isLoading}
        busy={listing.isFetching}
        empty="Маппингов нет. Создайте первый, чтобы заказы на этот SKU начали идти через поставщика."
        ariaLabel="Маппинги SKU"
      />
    </div>
  );
}

function FilterChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      type="button"
      onClick={onClick}
      variant={active ? "primary" : "secondary"}
      size="sm"
      aria-pressed={active}
    >
      {label}
    </Button>
  );
}

function formatError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string; title?: string } | null;
    return body?.detail ?? body?.title ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "неизвестная ошибка";
}
