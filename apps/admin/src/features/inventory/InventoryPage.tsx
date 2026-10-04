import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Select } from "@yupay/ui";
import { useId, useState } from "react";

import type {
  BulkUploadOut,
  CodeAdminListOut,
  CodeAdminOut,
  CodeState,
  SkuCountsOut,
} from "./types";
import type { SkuPickerRow } from "@/features/integrations/types";

import { Badge } from "@/components/Badge";
import { CopyId } from "@/components/CopyId";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { SkuPicker } from "@/features/integrations/pickers";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

const STATES: { value: CodeState | ""; label: string }[] = [
  { value: "", label: "Все" },
  { value: "available", label: "Доступны" },
  { value: "reserved", label: "Зарезервированы" },
  { value: "issued", label: "Выданы" },
  { value: "voided", label: "Воиднуты" },
];

export function InventoryPage() {
  // Ties each filter's visible <label> to its control; a plain sibling
  // label names nothing for a screen reader.
  const fieldId = useId();
  const qc = useQueryClient();
  // The picker's row, not a bare id: it carries the product kind the page
  // needs and spares it the full catalogue — 6150 SKUs in one `<select>`
  // was unusable long before it was slow.
  const [selected, setSelected] = useState<SkuPickerRow | null>(null);
  const skuId = selected?.id ?? "";
  const [state, setState] = useState<CodeState | "">("");
  const [codesText, setCodesText] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // The code warehouse only holds fixed-value voucher codes. Floating-amount
  // top-ups (e.g. `steam-wallet-usd`) are fulfilled by charging a supplier
  // API for whatever amount the customer entered — there is nothing to
  // upload, so the bulk-uploader is meaningless (and mildly dangerous —
  // pasting "codes" for a top-up SKU would just silently no-op) for them.
  const isVoucherSku = selected?.product_kind === "voucher";

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
      return apiGet<CodeAdminListOut>(`/api/v1/admin/inventory/codes?${params.toString()}`);
    },
    enabled: Boolean(skuId),
  });

  const uploadMutation = useMutation<BulkUploadOut, ApiError, { sku_id: string; codes: string[] }>({
    mutationFn: (body) => apiPost<BulkUploadOut>("/api/v1/admin/inventory/bulk-upload", body),
    onSuccess: (data) => {
      setFeedback(`Загружено ${data.succeeded}/${data.total}, дублей: ${data.duplicates}`);
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
        c.order_item_id ? <CopyId value={c.order_item_id} className="text-xs" /> : "—",
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
          <label
            htmlFor={`${fieldId}-f0`}
            className="text-xs font-medium uppercase text-[var(--text-secondary)]"
          >
            SKU
          </label>
          <div className="mt-1">
            <SkuPicker id={`${fieldId}-f0`} value={selected} onChange={setSelected} />
          </div>
        </div>

        {skuId && countsQuery.data && <CountsCard counts={countsQuery.data} />}
      </section>

      {skuId && isVoucherSku && (
        <section className="mb-6 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
          <h2 className="mb-2 text-sm font-semibold">Загрузить коды</h2>
          <p className="mb-2 text-xs text-[var(--text-secondary)]">
            По одному коду в строке (или через запятую / пробел). Дубли отсеются автоматически.
            Максимум 5000 за раз.
          </p>
          <textarea
            value={codesText}
            onChange={(e) => {
              setCodesText(e.target.value);
            }}
            rows={6}
            className="w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] p-3 font-mono text-xs"
            placeholder={"AAA-BBB-CCC\nXYZ-123-456"}
          />
          <div className="mt-3 flex items-center gap-3">
            <Button onClick={handleUpload} disabled={uploadMutation.isPending}>
              {uploadMutation.isPending ? "Загружаем…" : "Загрузить"}
            </Button>
            {feedback && <span className="text-sm text-[var(--success)]">{feedback}</span>}
            {error && <span className="text-sm text-[var(--danger)]">{error}</span>}
          </div>
        </section>
      )}

      {selected && !isVoucherSku && (
        <section className="mb-6 rounded-lg border border-dashed bg-[var(--bg-surface)] p-4 text-sm text-[var(--text-secondary)] shadow-[var(--shadow-sm)]">
          <h2 className="mb-2 text-sm font-semibold text-[var(--text-primary)]">
            Загрузка кодов недоступна
          </h2>
          <p>
            Этот SKU — товар с плавающей суммой (пополнение по факту оплаты, без склада кодов), а не
            ваучер. Загрузчик показывается только для SKU типа «voucher».
          </p>
        </section>
      )}

      {skuId && (
        <section>
          <div className="mb-3 flex items-center gap-3">
            <label
              htmlFor={`${fieldId}-f1`}
              className="text-xs font-medium uppercase text-[var(--text-secondary)]"
            >
              Фильтр
            </label>
            <Select
              id={`${fieldId}-f1`}
              value={state}
              onChange={(e) => {
                setState(e.target.value as CodeState | "");
              }}
              containerClassName="w-auto"
            >
              {STATES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          </div>
          {/* "Загрузи первые" on a failed fetch invites re-uploading a batch that
              is already in the warehouse — show the failure instead. */}
          {codesQuery.isError ? (
            <ErrorState
              description={extractApiMessage(codesQuery.error)}
              onRetry={() => void codesQuery.refetch()}
              retryPending={codesQuery.isFetching}
            />
          ) : (
            <DataTable
              rows={codesQuery.data?.items ?? []}
              columns={columns}
              rowKey={(c) => c.id}
              loading={codesQuery.isLoading}
              busy={codesQuery.isFetching}
              empty="Кодов нет. Загрузи первые сверху."
            />
          )}
        </section>
      )}

      {!skuId && (
        <div className="rounded-lg border bg-[var(--bg-surface)] p-10 text-center text-sm text-[var(--text-secondary)] shadow-[var(--shadow-sm)]">
          Выбери SKU, чтобы посмотреть счётчики и список кодов.
        </div>
      )}
    </div>
  );
}

function CountsCard({ counts }: { counts: SkuCountsOut }) {
  const cells: { label: string; value: number; tone: string }[] = [
    { label: "Доступно", value: counts.available, tone: "text-[var(--success)]" },
    { label: "Резерв", value: counts.reserved, tone: "text-[var(--text-primary)]" },
    { label: "Выдано", value: counts.issued, tone: "text-[var(--text-primary)]" },
    { label: "Воид", value: counts.voided, tone: "text-[var(--text-secondary)]" },
  ];
  return (
    <div className="grid grid-cols-4 gap-2 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      {cells.map((c) => (
        <div key={c.label} className="text-center">
          <div className={`text-2xl font-semibold ${c.tone}`}>{c.value}</div>
          <div className="text-xs uppercase text-[var(--text-secondary)]">{c.label}</div>
        </div>
      ))}
    </div>
  );
}

function StateBadge({ state }: { state: CodeState }) {
  const map: Record<CodeState, { label: string; cls: string }> = {
    available: { label: "доступен", cls: "bg-[var(--success-soft)] text-[var(--success-fg)]" },
    reserved: { label: "резерв", cls: "bg-[var(--warning-soft)] text-[var(--warning-fg)]" },
    issued: { label: "выдан", cls: "bg-[var(--info-soft)] text-[var(--info-fg)]" },
    voided: { label: "воид", cls: "bg-[var(--bg-muted)] text-[var(--text-secondary)]" },
  };
  const { label, cls } = map[state];
  return (
    <Badge tone={cls} dot>
      {label}
    </Badge>
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
