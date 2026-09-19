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
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { RulesTable } from "./RulesTable";
import { autoHintFor, disabledReasonFor, MODE_CARDS, ModeOption } from "./SourcingModeCards";
import { RoutePreview, SkuSummary } from "./SourcingSkuPanel";
import { SUPPLIER_OPTIONS } from "./supplierOptions";

import type { SourcingDecisionOut, SourcingMode, SourcingRuleListOut } from "./types";
import type { SkuPickerRow, SupplierMappingListOut } from "@/features/integrations/types";

import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";
import { SkuPicker } from "@/features/integrations/pickers";
import { FULFILMENT_ROUTES } from "@/features/integrations/types";
import { type ApiError, api, apiGet } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

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
  // Scoped to this SKU on purpose. Unfiltered, the endpoint answers its first
  // 200 rows ordered by `updated_at`, and production passed 200 active
  // mappings on 2026-09-19: `steam-wallet-usd` sat at rank 194 for NOVA and
  // 236 for G-Engine, so forcing G-Engine was refused with "no active
  // mapping" for a mapping that existed and simply fell off the page.
  const mappingsQuery = useQuery<SupplierMappingListOut>({
    queryKey: qk.integrationMappings({ supplierSlug: null, skuId: sku?.id ?? null }),
    queryFn: () =>
      apiGet<SupplierMappingListOut>(
        `/api/v1/admin/integrations/mappings?sku_id=${encodeURIComponent(sku?.id ?? "")}`,
      ),
    enabled: Boolean(sku),
  });
  const skuMapping = useMemo(() => {
    if (!sku) return null;
    return mappingsQuery.data?.items.find((m) => m.sku_id === sku.id && m.is_active) ?? null;
  }, [mappingsQuery.data, sku]);

  /** The label of the forced supplier when it needs a mapping and has none.
   *
   * `skuMapping` is "any active mapping", which is what auto-routing cares
   * about — but forcing G-Engine while only a G2B mapping exists would still
   * fail, so this check is per-supplier. */
  const missingMappingFor = useMemo(() => {
    const route = FULFILMENT_ROUTES.find((r) => r.slug === supplierSlug);
    if (!route?.mappings || !sku) return null;
    const has = mappingsQuery.data?.items.some(
      (m) => m.sku_id === sku.id && m.supplier_slug === supplierSlug && m.is_active,
    );
    return has ? null : route.label;
  }, [mappingsQuery.data, sku, supplierSlug]);

  // Whether the picked SKU already has an explicit rule — drives whether
  // this form reads as "editing" or "creating" (owner report: the form
  // used to offer "create" even for a SKU that already has one, and the
  // PUT silently replaced it, so a replacement looked like an addition).
  // `sku_sourcing_rules`'s primary key is `sku_id`, so there is at most
  // one, and this is that one.
  const existingRule = useMemo(() => {
    if (!sku) return null;
    return rulesQuery.data?.items.find((r) => r.sku_id === sku.id) ?? null;
  }, [sku, rulesQuery.data]);

  // When the operator picks a SKU, prefill the form with its existing
  // rule (or reset to auto if it has none).
  useEffect(() => {
    if (!sku) return;
    if (existingRule) {
      setMode(existingRule.mode);
      setSupplierSlug(existingRule.supplier_slug ?? "g2b");
    } else {
      setMode("auto");
      setSupplierSlug("g2b");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sku?.id, existingRule]);

  const save = useMutation<unknown, ApiError>({
    // AGENTS.md §9: every state-changing request carries a fresh
    // Idempotency-Key, minted per attempt (here, inside mutationFn — same
    // "per attempt, never reused" policy `bulkSwitch.ts` documents, just
    // for a single-SKU write instead of a chunked one).
    mutationFn: () => {
      if (mode === "auto") {
        // "Авто" === no explicit rule. Saving auto deletes any override.
        return api(`/api/v1/admin/sourcing/rules/${sku?.id ?? ""}`, {
          method: "DELETE",
          headers: { "Idempotency-Key": crypto.randomUUID() },
        });
      }
      return api(`/api/v1/admin/sourcing/rules/${sku?.id ?? ""}`, {
        method: "PUT",
        headers: { "Idempotency-Key": crypto.randomUUID() },
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
      toast.error(extractApiMessage(err));
    },
  });

  const remove = useMutation<void, ApiError, string>({
    // Same gap, same file, same rule — see the comment on `save` above.
    mutationFn: (skuId) =>
      api<void>(`/api/v1/admin/sourcing/rules/${skuId}`, {
        method: "DELETE",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      }),
    onSuccess: () => {
      toast.success("Правило удалено — SKU вернулся в авто");
      void qc.invalidateQueries({ queryKey: qk.sourcingRules() });
      void qc.invalidateQueries({ queryKey: qk.sourcingDecision(sku?.id ?? "") });
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  // Defence in depth alongside the mode card's own `disabled` — the card
  // can't be clicked into a disallowed mode, but this also blocks Save if
  // a legacy rule row left the form pre-filled with one (e.g. a top_up SKU
  // with a stray `force_inventory` row from before this guard existed).
  const modeDisabled = sku !== null && disabledReasonFor(mode, sku) !== null;
  const canSave =
    sku !== null && !modeDisabled && (mode !== "force_supplier" || supplierSlug.trim().length > 0);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Маршрутизация (sourcing)"
        description="Откуда брать товар при оплате каждого SKU — из склада кодов или у поставщика."
        actions={
          <Link to="/sourcing/brands" className="text-sm text-[var(--accent)] hover:underline">
            Сравнить поставщиков по бренду →
          </Link>
        }
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
              {existingRule && (
                <p className="mb-2 rounded-md bg-[var(--bg-accent-soft)] px-3 py-2 text-xs text-[var(--accent-soft-fg)]">
                  У этого SKU уже есть правило (
                  {MODE_CARDS.find((c) => c.value === existingRule.mode)?.label ??
                    existingRule.mode}
                  {existingRule.supplier_slug ? ` · ${existingRule.supplier_slug}` : ""}) — форма
                  ниже его редактирует, а не создаёт новое.
                </p>
              )}
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                {MODE_CARDS.map((card) => (
                  <ModeOption
                    key={card.value}
                    card={card}
                    selected={mode === card.value}
                    autoHint={card.value === "auto" ? autoHintFor(sku, skuMapping) : null}
                    disabledReason={disabledReasonFor(card.value, sku)}
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
                {missingMappingFor && (
                  <p className="mt-2 text-xs text-[var(--danger)]">
                    У этого SKU нет активного маппинга на {missingMappingFor} — заказ упадёт в
                    ошибку. Сначала создайте маппинг в «Интеграции → Маппинги».
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
                    : existingRule
                      ? "Заменить правило"
                      : "Создать правило"}
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
        <RulesTable
          rules={rulesQuery.data?.items ?? []}
          loading={rulesQuery.isLoading}
          onDelete={(skuId) => {
            remove.mutate(skuId);
          }}
        />
      </section>
    </div>
  );
}
