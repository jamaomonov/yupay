/** Sourcing — where each SKU gets fulfilled from.
 *
 * Rewritten from three bare <select>s into a guided editor:
 *   1. Pick a SKU (searchable combobox, shows product kind).
 *   2. See what happens today (live route preview + mapping status).
 *   3. Choose a mode (cards, each explaining the outcome for THIS sku).
 *   4. For "supplier", pick which one.
 *
 * The "Авто" card spells out the kind-aware default so operators
 * understand they often don't need a rule at all — top_up with a
 * mapping already routes to the supplier; voucher already tries the
 * warehouse first. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { ArrowRight, Boxes, Hand, Sparkles, Truck, Warehouse } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { SourcingDecisionOut, SourcingMode, SourcingRuleListOut } from "./types";

import { Badge } from "@/components/Badge";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { SkuPicker } from "@/features/integrations/pickers";
import type { SkuPickerRow, SupplierMappingListOut } from "@/features/integrations/types";
import { type ApiError, api, apiGet } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { qk } from "@/lib/queryKeys";

// Suppliers that make sense as a ``force_supplier`` target today.
const SUPPLIER_OPTIONS: { slug: string; label: string; note: string }[] = [
  { slug: "g2b", label: "G2Bulk", note: "реальный поставщик" },
  { slug: "mock", label: "Mock", note: "только dev" },
];

interface ModeCard {
  value: SourcingMode;
  label: string;
  icon: typeof Sparkles;
  blurb: string;
}

const MODE_CARDS: ModeCard[] = [
  {
    value: "auto",
    label: "Авто",
    icon: Sparkles,
    blurb: "Система решает по типу товара. Обычно ничего настраивать не нужно.",
  },
  {
    value: "force_supplier",
    label: "Только поставщик",
    icon: Truck,
    blurb: "Всегда выкупать у поставщика, минуя склад. Нужно выбрать какого.",
  },
  {
    value: "force_inventory",
    label: "Только склад",
    icon: Warehouse,
    blurb: "Выдавать только из склада кодов. Нет кодов — заказ упадёт в ошибку.",
  },
  {
    value: "manual",
    label: "Вручную",
    icon: Hand,
    blurb: "Без автоматики — заказ попадёт в очередь ручной выдачи оператору.",
  },
];

export function SourcingPage() {
  const qc = useQueryClient();
  const toast = useToast();

  const [sku, setSku] = useState<SkuPickerRow | null>(null);
  const [mode, setMode] = useState<SourcingMode>("auto");
  const [supplierSlug, setSupplierSlug] = useState<string>("g2b");

  const rulesQuery = useQuery<SourcingRuleListOut>({
    queryKey: qk.sourcingRules(),
    queryFn: () => apiGet<SourcingRuleListOut>("/api/v1/admin/sourcing/rules"),
  });

  // Live route the backend would take for the picked SKU right now.
  const decisionQuery = useQuery<SourcingDecisionOut>({
    queryKey: qk.sourcingDecision(sku?.id ?? ""),
    queryFn: () => apiGet<SourcingDecisionOut>(`/api/v1/admin/sourcing/rules/${sku?.id ?? ""}`),
    enabled: Boolean(sku),
  });

  // Does this SKU have an active supplier mapping? Drives the "Авто"
  // card's explanation + a status chip.
  const mappingsQuery = useQuery<SupplierMappingListOut>({
    queryKey: qk.integrationMappings({ supplierSlug: null }),
    queryFn: () => apiGet<SupplierMappingListOut>("/api/v1/admin/integrations/mappings"),
  });
  const skuMapping = useMemo(() => {
    if (!sku) return null;
    return mappingsQuery.data?.items.find((m) => m.sku_id === sku.id && m.is_active) ?? null;
  }, [mappingsQuery.data, sku]);

  // When the operator picks a SKU, prefill the form with its existing
  // rule (or reset to auto if it has none).
  useEffect(() => {
    if (!sku) return;
    const existing = rulesQuery.data?.items.find((r) => r.sku_id === sku.id);
    if (existing) {
      setMode(existing.mode);
      setSupplierSlug(existing.supplier_slug ?? "g2b");
    } else {
      setMode("auto");
      setSupplierSlug("g2b");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sku?.id, rulesQuery.data]);

  const save = useMutation<unknown, ApiError>({
    mutationFn: () => {
      if (mode === "auto") {
        // "Авто" === no explicit rule. Saving auto deletes any override.
        return api(`/api/v1/admin/sourcing/rules/${sku?.id ?? ""}`, { method: "DELETE" });
      }
      return api(`/api/v1/admin/sourcing/rules/${sku?.id ?? ""}`, {
        method: "PUT",
        body: JSON.stringify({
          mode,
          supplier_slug: mode === "force_supplier" ? supplierSlug : null,
        }),
      });
    },
    onSuccess: () => {
      toast.success(mode === "auto" ? "Сброшено в авто" : "Правило сохранено");
      void qc.invalidateQueries({ queryKey: qk.sourcingRules() });
      void qc.invalidateQueries({ queryKey: qk.sourcingDecision(sku?.id ?? "") });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const remove = useMutation<void, ApiError, string>({
    mutationFn: (skuId) => api<void>(`/api/v1/admin/sourcing/rules/${skuId}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Правило удалено — SKU вернулся в авто");
      void qc.invalidateQueries({ queryKey: qk.sourcingRules() });
      void qc.invalidateQueries({ queryKey: qk.sourcingDecision(sku?.id ?? "") });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const canSave = sku !== null && (mode !== "force_supplier" || supplierSlug.trim().length > 0);

  const columns: Column<SourcingRuleListOut["items"][number]>[] = [
    {
      key: "sku",
      header: "SKU",
      render: (r) => (
        <code className="font-mono text-xs text-[var(--text-secondary)]">
          {r.sku_id.slice(0, 8)}…
        </code>
      ),
      className: "w-32",
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
      render: (r) =>
        r.supplier_slug ? (
          <code className="text-xs">{r.supplier_slug}</code>
        ) : (
          <span className="text-[var(--text-tertiary)]">—</span>
        ),
      className: "w-32",
    },
    {
      key: "updated",
      header: "Обновлено",
      render: (r) =>
        new Date(r.updated_at).toLocaleString("ru", {
          day: "2-digit",
          month: "2-digit",
          year: "2-digit",
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
            if (window.confirm("Удалить правило? SKU вернётся в режим авто.")) {
              remove.mutate(r.sku_id);
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
    <div className="space-y-6">
      <PageHeader
        title="Маршрутизация (sourcing)"
        description="Откуда брать товар при оплате каждого SKU — из склада кодов или у поставщика."
      />

      <section className="space-y-5 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-5 shadow-[var(--shadow-sm)]">
        <div>
          <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
            SKU
          </label>
          <SkuPicker value={sku} onChange={setSku} />
        </div>

        {sku && (
          <>
            <SkuSummary sku={sku} mapping={skuMapping} />

            {decisionQuery.data && (
              <RoutePreview decision={decisionQuery.data} loading={decisionQuery.isFetching} />
            )}

            <div>
              <span className="mb-2 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
                Режим
              </span>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {MODE_CARDS.map((card) => (
                  <ModeOption
                    key={card.value}
                    card={card}
                    selected={mode === card.value}
                    autoHint={card.value === "auto" ? autoHintFor(sku, skuMapping) : null}
                    onSelect={() => {
                      setMode(card.value);
                    }}
                  />
                ))}
              </div>
            </div>

            {mode === "force_supplier" && (
              <div>
                <span className="mb-2 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
                  Поставщик
                </span>
                <div className="flex flex-wrap gap-2">
                  {SUPPLIER_OPTIONS.map((s) => (
                    <button
                      key={s.slug}
                      type="button"
                      onClick={() => {
                        setSupplierSlug(s.slug);
                      }}
                      aria-pressed={supplierSlug === s.slug}
                      className={[
                        "flex flex-col items-start gap-0.5 rounded-md border px-3 py-1.5 text-left text-sm transition-colors",
                        supplierSlug === s.slug
                          ? "border-[var(--accent)] bg-[var(--bg-accent-soft)]"
                          : "border-[var(--border-default)] hover:bg-[var(--bg-muted)]",
                      ].join(" ")}
                    >
                      <span className="font-medium">{s.label}</span>
                      <span className="text-[10px] text-[var(--text-tertiary)]">{s.note}</span>
                    </button>
                  ))}
                </div>
                {supplierSlug === "g2b" && skuMapping === null && (
                  <p className="mt-2 text-xs text-[var(--danger)]">
                    У этого SKU нет активного маппинга на G2B — заказ упадёт в ошибку. Сначала
                    создайте маппинг в «Интеграции → Маппинги».
                  </p>
                )}
              </div>
            )}

            <div className="flex items-center gap-3 border-t border-[var(--border-subtle)] pt-4">
              <Button
                onClick={() => {
                  save.mutate();
                }}
                disabled={!canSave || save.isPending}
              >
                {save.isPending
                  ? "Сохраняем…"
                  : mode === "auto"
                    ? "Применить (авто)"
                    : "Сохранить правило"}
              </Button>
              <span className="text-xs text-[var(--text-tertiary)]">
                «Авто» снимает любое явное правило с этого SKU.
              </span>
            </div>
          </>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
          Явные правила
        </h2>
        <DataTable
          rows={rulesQuery.data?.items ?? []}
          columns={columns}
          rowKey={(r) => r.sku_id}
          loading={rulesQuery.isLoading}
          empty="Явных правил нет — все SKU работают в режиме авто."
        />
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SKU summary
// ---------------------------------------------------------------------------

function SkuSummary({
  sku,
  mapping,
}: {
  sku: SkuPickerRow;
  mapping: { supplier_slug: string } | null;
}) {
  const isTopUp = sku.product_kind === "top_up";
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md bg-[var(--bg-muted)] px-3 py-2 text-sm">
      <span className="font-medium">{sku.product_name}</span>
      <code className="text-xs text-[var(--text-secondary)]">{sku.sku_code}</code>
      <Badge
        tone={
          isTopUp
            ? "bg-[var(--info-soft)] text-[var(--info-fg)]"
            : "bg-[var(--bg-surface)] text-[var(--text-secondary)]"
        }
      >
        {isTopUp ? "игровой топ-ап" : "ваучер"}
      </Badge>
      {mapping ? (
        <Badge tone="bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]" dot>
          маппинг: {mapping.supplier_slug}
        </Badge>
      ) : (
        <Badge tone="bg-[var(--bg-surface)] text-[var(--text-tertiary)]">нет маппинга</Badge>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Route preview
// ---------------------------------------------------------------------------

function RoutePreview({ decision, loading }: { decision: SourcingDecisionOut; loading: boolean }) {
  return (
    <div className="rounded-md border border-dashed border-[var(--border-default)] p-3">
      <div className="mb-2 flex items-center gap-2 text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
        Что произойдёт при оплате
        {loading && <span className="text-[var(--text-tertiary)]">· обновляем…</span>}
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <RouteNode route={decision.primary} primary />
        {decision.fallback && !decision.strict && (
          <>
            <span className="text-[var(--text-tertiary)]">
              <ArrowRight className="size-4" aria-hidden />
            </span>
            <span className="text-xs text-[var(--text-tertiary)]">если не вышло →</span>
            <RouteNode route={decision.fallback} primary={false} />
          </>
        )}
        {decision.strict && (
          <span className="text-xs text-[var(--text-tertiary)]">(без запасного варианта)</span>
        )}
      </div>
      {!decision.rule_present && (
        <p className="mt-2 text-[10px] text-[var(--text-tertiary)]">
          Режим «авто» — правило не задано явно.
        </p>
      )}
    </div>
  );
}

function RouteNode({ route, primary }: { route: string; primary: boolean }) {
  const { icon: Icon, label } = describeRoute(route);
  return (
    <span
      className={[
        "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-sm",
        primary
          ? "bg-[var(--bg-accent-soft)] font-medium text-[var(--accent-soft-fg)]"
          : "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
      ].join(" ")}
    >
      <Icon className="size-4" aria-hidden />
      {label}
    </span>
  );
}

function describeRoute(route: string): { icon: typeof Boxes; label: string } {
  if (route === "inventory") return { icon: Warehouse, label: "Склад кодов" };
  const slug = route.startsWith("supplier:") ? route.slice("supplier:".length) : route;
  if (slug === "manual") return { icon: Hand, label: "Ручная выдача" };
  if (slug === "g2b") return { icon: Truck, label: "Поставщик G2Bulk" };
  if (slug === "mock") return { icon: Boxes, label: "Mock (dev)" };
  return { icon: Truck, label: `Поставщик ${slug}` };
}

// ---------------------------------------------------------------------------
// Mode option card
// ---------------------------------------------------------------------------

function ModeOption({
  card,
  selected,
  autoHint,
  onSelect,
}: {
  card: ModeCard;
  selected: boolean;
  autoHint: string | null;
  onSelect: () => void;
}) {
  const Icon = card.icon;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={[
        "flex flex-col gap-1.5 rounded-md border p-3 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
        selected
          ? "border-[var(--accent)] bg-[var(--bg-accent-soft)]"
          : "border-[var(--border-default)] hover:bg-[var(--bg-muted)]",
      ].join(" ")}
    >
      <span className="flex items-center gap-2">
        <Icon className="size-4 text-[var(--accent)]" aria-hidden />
        <span className="font-medium">{card.label}</span>
      </span>
      <span className="text-xs text-[var(--text-secondary)]">{card.blurb}</span>
      {autoHint && (
        <span className="mt-0.5 rounded bg-[var(--bg-surface)] px-2 py-1 text-[11px] text-[var(--text-secondary)]">
          {autoHint}
        </span>
      )}
    </button>
  );
}

/** Human explanation of what "auto" resolves to for THIS sku. */
function autoHintFor(sku: SkuPickerRow, mapping: { supplier_slug: string } | null): string {
  if (sku.product_kind === "top_up") {
    return mapping
      ? `Сейчас: поставщик ${mapping.supplier_slug} → при отказе ручная выдача.`
      : "Сейчас: ручная выдача (нет маппинга на поставщика).";
  }
  return mapping
    ? `Сейчас: склад → при пустом складе поставщик ${mapping.supplier_slug}.`
    : "Сейчас: склад → при пустом складе mock (dev) / ошибка (prod).";
}

// ---------------------------------------------------------------------------
// shared
// ---------------------------------------------------------------------------

function ModeBadge({ mode }: { mode: SourcingMode }) {
  const map: Record<SourcingMode, { label: string; cls: string }> = {
    auto: { label: "авто", cls: "bg-[var(--bg-muted)] text-[var(--text-secondary)]" },
    force_inventory: {
      label: "только склад",
      cls: "bg-[var(--success-soft)] text-[var(--success-fg)]",
    },
    force_supplier: {
      label: "только поставщик",
      cls: "bg-[var(--info-soft)] text-[var(--info-fg)]",
    },
    manual: { label: "вручную", cls: "bg-[var(--warning-soft)] text-[var(--warning-fg)]" },
  };
  const { label, cls } = map[mode];
  return (
    <Badge tone={cls} dot={mode !== "auto"}>
      {label}
    </Badge>
  );
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
