import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { ApiError, api, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { Product, Sku } from "@/features/catalog/types";

import type {
  SourcingDecisionOut,
  SourcingMode,
  SourcingRuleListOut,
  SourcingRuleOut,
} from "./types";

const MODES: { value: SourcingMode; label: string; hint: string }[] = [
  {
    value: "auto",
    label: "Авто",
    hint: "Склад → fallback на поставщика по умолчанию.",
  },
  {
    value: "force_inventory",
    label: "Только склад",
    hint: "Не звать поставщика; нет кодов — задача упадёт.",
  },
  {
    value: "force_supplier",
    label: "Только поставщик",
    hint: "Игнорировать склад. Нужен supplier_slug.",
  },
  {
    value: "manual",
    label: "Вручную",
    hint: "Без поставщика — оператор обработает в очереди ручной выдачи.",
  },
];

export function SourcingPage() {
  const qc = useQueryClient();
  const [selectedSkuId, setSelectedSkuId] = useState<string>("");
  const [mode, setMode] = useState<SourcingMode>("auto");
  const [supplierSlug, setSupplierSlug] = useState<string>("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const skusQuery = useQuery<Sku[]>({
    queryKey: qk.skus(),
    queryFn: () => apiGet<Sku[]>("/api/v1/admin/catalog/skus"),
  });
  const productsQuery = useQuery<Product[]>({
    queryKey: qk.products(),
    queryFn: () => apiGet<Product[]>("/api/v1/admin/catalog/products"),
  });
  const rulesQuery = useQuery<SourcingRuleListOut>({
    queryKey: qk.sourcingRules(),
    queryFn: () =>
      apiGet<SourcingRuleListOut>("/api/v1/admin/sourcing/rules"),
  });

  const productById = useMemo(() => {
    const map = new Map<string, Product>();
    for (const p of productsQuery.data ?? []) map.set(p.id, p);
    return map;
  }, [productsQuery.data]);
  const skuById = useMemo(() => {
    const map = new Map<string, Sku>();
    for (const s of skusQuery.data ?? []) map.set(s.id, s);
    return map;
  }, [skusQuery.data]);

  const decisionQuery = useQuery<SourcingDecisionOut>({
    queryKey: qk.sourcingDecision(selectedSkuId),
    queryFn: () =>
      apiGet<SourcingDecisionOut>(
        `/api/v1/admin/sourcing/rules/${selectedSkuId}`,
      ),
    enabled: Boolean(selectedSkuId),
  });

  const upsertMutation = useMutation<
    SourcingRuleOut,
    ApiError,
    { skuId: string; mode: SourcingMode; supplier_slug: string | null }
  >({
    mutationFn: ({ skuId, ...body }) =>
      api<SourcingRuleOut>(`/api/v1/admin/sourcing/rules/${skuId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      setFeedback("Правило сохранено.");
      setError(null);
      void qc.invalidateQueries({ queryKey: qk.sourcingRules() });
      void qc.invalidateQueries({
        queryKey: qk.sourcingDecision(selectedSkuId),
      });
    },
    onError: (err) => {
      setError(formatApiError(err));
      setFeedback(null);
    },
  });

  const deleteMutation = useMutation<void, ApiError, string>({
    mutationFn: (skuId) =>
      api<void>(`/api/v1/admin/sourcing/rules/${skuId}`, { method: "DELETE" }),
    onSuccess: (_void, skuId) => {
      setFeedback("Правило удалено — SKU вернулся в auto.");
      setError(null);
      void qc.invalidateQueries({ queryKey: qk.sourcingRules() });
      void qc.invalidateQueries({ queryKey: qk.sourcingDecision(skuId) });
    },
    onError: (err) => {
      setError(formatApiError(err));
      setFeedback(null);
    },
  });

  const handleSave = () => {
    setError(null);
    setFeedback(null);
    if (!selectedSkuId) {
      setError("Выберите SKU.");
      return;
    }
    if (mode === "force_supplier" && !supplierSlug.trim()) {
      setError("Для force_supplier нужен supplier_slug.");
      return;
    }
    upsertMutation.mutate({
      skuId: selectedSkuId,
      mode,
      supplier_slug: mode === "force_supplier" ? supplierSlug.trim() : null,
    });
  };

  const columns: Column<SourcingRuleOut>[] = [
    {
      key: "sku",
      header: "SKU",
      render: (r) => {
        const sku = skuById.get(r.sku_id);
        const product = sku ? productById.get(sku.product_id) : undefined;
        const name =
          product?.translations.find((t) => t.locale === "ru")?.name ??
          product?.slug ??
          "?";
        return (
          <div className="flex flex-col">
            <span className="text-sm">{name}</span>
            <code className="text-xs text-[--text-secondary]">
              {sku?.sku_code ?? r.sku_id.slice(0, 8)}
            </code>
          </div>
        );
      },
    },
    {
      key: "mode",
      header: "Режим",
      render: (r) => <ModeBadge mode={r.mode} />,
      className: "w-44",
    },
    {
      key: "supplier",
      header: "Поставщик",
      render: (r) => r.supplier_slug ?? "—",
      className: "w-32",
    },
    {
      key: "updated",
      header: "Обновлено",
      render: (r) =>
        new Date(r.updated_at).toLocaleString("ru", {
          year: "2-digit",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }),
      className: "w-40",
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={(ev) => {
            ev.stopPropagation();
            if (window.confirm("Удалить правило? SKU вернётся в режим auto.")) {
              deleteMutation.mutate(r.sku_id);
            }
          }}
        >
          Удалить
        </Button>
      ),
      className: "w-24 text-right",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Sourcing"
        description="Правила маршрутизации: где брать товар — из склада или у поставщика."
      />

      <section className="mb-6 rounded-lg border bg-[--bg-surface] p-4">
        <h2 className="mb-3 text-sm font-semibold">Назначить / изменить правило</h2>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div>
            <label className="text-xs font-medium uppercase text-[--text-secondary]">
              SKU
            </label>
            <select
              value={selectedSkuId}
              onChange={(e) => setSelectedSkuId(e.target.value)}
              className="mt-1 h-10 w-full rounded-md border border-[--border-default] bg-[--bg-surface] px-3 text-sm"
            >
              <option value="">— Выбрать —</option>
              {skusQuery.data?.map((sku) => {
                const product = productById.get(sku.product_id);
                const productName =
                  product?.translations.find((t) => t.locale === "ru")?.name ??
                  product?.slug ??
                  "";
                return (
                  <option key={sku.id} value={sku.id}>
                    {productName} — {sku.sku_code}
                  </option>
                );
              })}
            </select>
          </div>
          <div>
            <label className="text-xs font-medium uppercase text-[--text-secondary]">
              Режим
            </label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value as SourcingMode)}
              className="mt-1 h-10 w-full rounded-md border border-[--border-default] bg-[--bg-surface] px-3 text-sm"
            >
              {MODES.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-[--text-secondary]">
              {MODES.find((m) => m.value === mode)?.hint}
            </p>
          </div>
          <div>
            <label className="text-xs font-medium uppercase text-[--text-secondary]">
              Supplier slug
            </label>
            <input
              type="text"
              value={supplierSlug}
              onChange={(e) => setSupplierSlug(e.target.value)}
              disabled={mode !== "force_supplier"}
              placeholder="mock / steam / riot / …"
              className="mt-1 h-10 w-full rounded-md border border-[--border-default] bg-[--bg-surface] px-3 text-sm disabled:opacity-50"
            />
          </div>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <Button
            onClick={handleSave}
            disabled={upsertMutation.isPending || !selectedSkuId}
          >
            {upsertMutation.isPending ? "Сохраняем…" : "Сохранить правило"}
          </Button>
          {selectedSkuId && decisionQuery.data && (
            <DecisionPreview decision={decisionQuery.data} />
          )}
          {feedback && (
            <span className="text-sm text-[--success]">{feedback}</span>
          )}
          {error && <span className="text-sm text-[--danger]">{error}</span>}
        </div>
      </section>

      <h2 className="mb-3 text-sm font-semibold uppercase text-[--text-secondary]">
        Активные правила
      </h2>
      <DataTable
        rows={rulesQuery.data?.items ?? []}
        columns={columns}
        rowKey={(r) => r.sku_id}
        empty="Правил нет — все SKU работают в режиме auto."
      />
    </div>
  );
}

function ModeBadge({ mode }: { mode: SourcingMode }) {
  const map: Record<SourcingMode, { label: string; cls: string }> = {
    auto: { label: "auto", cls: "bg-[--bg-muted] text-[--text-secondary]" },
    force_inventory: {
      label: "склад",
      cls: "bg-[--success-soft] text-[--success-fg]",
    },
    force_supplier: { label: "поставщик", cls: "bg-[--info-soft] text-[--info-fg]" },
    manual: { label: "вручную", cls: "bg-[--warning-soft] text-[--warning-fg]" },
  };
  const { label, cls } = map[mode];
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>
      {label}
    </span>
  );
}

function DecisionPreview({ decision }: { decision: SourcingDecisionOut }) {
  return (
    <span className="text-xs text-[--text-secondary]">
      Сейчас: <code className="text-[--text-primary]">{decision.primary}</code>
      {decision.fallback && (
        <>
          {" → "}
          <code className="text-[--text-primary]">{decision.fallback}</code>
        </>
      )}
      {decision.strict && " (strict)"}
    </span>
  );
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
