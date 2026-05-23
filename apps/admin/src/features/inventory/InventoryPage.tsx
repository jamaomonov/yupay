import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { Product, Sku } from "@/features/catalog/types";

import type {
  BulkUploadOut,
  CodeAdminListOut,
  CodeAdminOut,
  CodeState,
  SkuCountsOut,
} from "./types";

const STATES: { value: CodeState | ""; label: string }[] = [
  { value: "", label: "Все" },
  { value: "available", label: "Доступны" },
  { value: "reserved", label: "Зарезервированы" },
  { value: "issued", label: "Выданы" },
  { value: "voided", label: "Воиднуты" },
];

export function InventoryPage() {
  const qc = useQueryClient();
  const [skuId, setSkuId] = useState<string>("");
  const [state, setState] = useState<CodeState | "">("");
  const [codesText, setCodesText] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const productsQuery = useQuery<Product[]>({
    queryKey: qk.products(),
    queryFn: () => apiGet<Product[]>("/api/v1/admin/catalog/products"),
  });
  const skusQuery = useQuery<Sku[]>({
    queryKey: qk.skus(),
    queryFn: () => apiGet<Sku[]>("/api/v1/admin/catalog/skus"),
  });
  const productById = useMemo(() => {
    const map = new Map<string, Product>();
    for (const p of productsQuery.data ?? []) map.set(p.id, p);
    return map;
  }, [productsQuery.data]);

  const countsQuery = useQuery<SkuCountsOut>({
    queryKey: qk.inventoryCounts(skuId),
    queryFn: () => apiGet<SkuCountsOut>(`/api/v1/admin/inventory/sku/${skuId}`),
    enabled: Boolean(skuId),
  });

  const codesQuery = useQuery<CodeAdminListOut>({
    queryKey: qk.inventoryCodes({ skuId: skuId || null, state: state || null }),
    queryFn: () => {
      const params = new URLSearchParams();
      if (skuId) params.set("sku_id", skuId);
      if (state) params.set("state", state);
      params.set("limit", "200");
      return apiGet<CodeAdminListOut>(
        `/api/v1/admin/inventory/codes?${params.toString()}`,
      );
    },
    enabled: Boolean(skuId),
  });

  const uploadMutation = useMutation<
    BulkUploadOut,
    ApiError,
    { sku_id: string; codes: string[] }
  >({
    mutationFn: (body) =>
      apiPost<BulkUploadOut>("/api/v1/admin/inventory/bulk-upload", body),
    onSuccess: (data) => {
      setFeedback(
        `Загружено ${data.succeeded}/${data.total}, дублей: ${data.duplicates}`,
      );
      setError(null);
      setCodesText("");
      void qc.invalidateQueries({ queryKey: qk.inventoryCounts(skuId) });
      void qc.invalidateQueries({
        queryKey: qk.inventoryCodes({ skuId, state: state || null }),
      });
    },
    onError: (err) => {
      setError(formatApiError(err));
      setFeedback(null);
    },
  });

  const handleUpload = () => {
    setError(null);
    setFeedback(null);
    if (!skuId) {
      setError("Выберите SKU.");
      return;
    }
    const codes = codesText
      .split(/[\s,;]+/)
      .map((c) => c.trim())
      .filter(Boolean);
    if (codes.length === 0) {
      setError("Вставьте хотя бы один код.");
      return;
    }
    if (codes.length > 5000) {
      setError(`Максимум 5000 кодов за раз (введено ${codes.length}).`);
      return;
    }
    uploadMutation.mutate({ sku_id: skuId, codes });
  };

  const columns: Column<CodeAdminOut>[] = [
    {
      key: "code",
      header: "Код",
      render: (c) => <code className="break-all text-xs">{c.code}</code>,
    },
    {
      key: "state",
      header: "Статус",
      render: (c) => <StateBadge state={c.state} />,
      className: "w-32",
    },
    {
      key: "order",
      header: "Order item",
      render: (c) =>
        c.order_item_id ? (
          <code className="text-xs">{c.order_item_id.slice(0, 8)}…</code>
        ) : (
          "—"
        ),
    },
    {
      key: "issued",
      header: "Выдан",
      render: (c) => formatDate(c.issued_at),
      className: "w-40",
    },
    {
      key: "created",
      header: "Загружен",
      render: (c) => formatDate(c.created_at),
      className: "w-40",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Склад"
        description="Шифрованное хранилище кодов. Bulk-upload, статусы, поиск."
      />

      <section className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <label className="text-xs font-medium uppercase text-[--text-secondary]">
            SKU
          </label>
          <select
            value={skuId}
            onChange={(e) => setSkuId(e.target.value)}
            className="mt-1 h-10 w-full rounded-md border border-[--border-default] bg-[--bg-surface] px-3 text-sm"
          >
            <option value="">— Выбрать —</option>
            {skusQuery.data?.map((sku) => {
              const product = productById.get(sku.product_id);
              const productName =
                product?.translations.find((t) => t.locale === "ru")?.name ??
                product?.slug ??
                sku.product_id.slice(0, 8);
              return (
                <option key={sku.id} value={sku.id}>
                  {productName} — {sku.sku_code}
                </option>
              );
            })}
          </select>
        </div>

        {skuId && countsQuery.data && (
          <CountsCard counts={countsQuery.data} />
        )}
      </section>

      {skuId && (
        <section className="mb-6 rounded-lg border bg-[--bg-surface] p-4">
          <h2 className="mb-2 text-sm font-semibold">Загрузить коды</h2>
          <p className="mb-2 text-xs text-[--text-secondary]">
            По одному коду в строке (или через запятую / пробел). Дубли отсеются
            автоматически. Максимум 5000 за раз.
          </p>
          <textarea
            value={codesText}
            onChange={(e) => setCodesText(e.target.value)}
            rows={6}
            className="w-full rounded-md border border-[--border-default] bg-[--bg-surface] p-3 font-mono text-xs"
            placeholder={"AAA-BBB-CCC\nXYZ-123-456"}
          />
          <div className="mt-3 flex items-center gap-3">
            <Button
              onClick={handleUpload}
              disabled={uploadMutation.isPending}
            >
              {uploadMutation.isPending ? "Загружаем…" : "Загрузить"}
            </Button>
            {feedback && (
              <span className="text-sm text-[--success]">{feedback}</span>
            )}
            {error && <span className="text-sm text-[--danger]">{error}</span>}
          </div>
        </section>
      )}

      {skuId && (
        <section>
          <div className="mb-3 flex items-center gap-3">
            <label className="text-xs font-medium uppercase text-[--text-secondary]">
              Фильтр
            </label>
            <select
              value={state}
              onChange={(e) => setState(e.target.value as CodeState | "")}
              className="h-9 rounded-md border border-[--border-default] bg-[--bg-surface] px-3 text-sm"
            >
              {STATES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
          <DataTable
            rows={codesQuery.data?.items ?? []}
            columns={columns}
            rowKey={(c) => c.id}
            empty="Кодов нет. Загрузи первые сверху."
          />
        </section>
      )}

      {!skuId && (
        <div className="rounded-lg border bg-[--bg-surface] p-10 text-center text-sm text-[--text-secondary]">
          Выбери SKU, чтобы посмотреть счётчики и список кодов.
        </div>
      )}
    </div>
  );
}

function CountsCard({ counts }: { counts: SkuCountsOut }) {
  const cells: { label: string; value: number; tone: string }[] = [
    { label: "Доступно", value: counts.available, tone: "text-[--success]" },
    { label: "Резерв", value: counts.reserved, tone: "text-[--text-primary]" },
    { label: "Выдано", value: counts.issued, tone: "text-[--text-primary]" },
    { label: "Воид", value: counts.voided, tone: "text-[--text-secondary]" },
  ];
  return (
    <div className="grid grid-cols-4 gap-2 rounded-lg border bg-[--bg-surface] p-4">
      {cells.map((c) => (
        <div key={c.label} className="text-center">
          <div className={`text-2xl font-semibold ${c.tone}`}>{c.value}</div>
          <div className="text-xs uppercase text-[--text-secondary]">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function StateBadge({ state }: { state: CodeState }) {
  const map: Record<CodeState, { label: string; cls: string }> = {
    available: { label: "доступен", cls: "bg-[--success-soft] text-[--success-fg]" },
    reserved: { label: "резерв", cls: "bg-[--warning-soft] text-[--warning-fg]" },
    issued: { label: "выдан", cls: "bg-[--info-soft] text-[--info-fg]" },
    voided: { label: "воид", cls: "bg-[--bg-muted] text-[--text-secondary]" },
  };
  const { label, cls } = map[state];
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
