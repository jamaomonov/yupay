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

import type {
  SourcingDecisionOut,
  SourcingMode,
  SourcingRuleListOut,
  SourcingRuleOut,
} from "./types";
import type { SkuPickerRow, SupplierMappingListOut } from "@/features/integrations/types";

import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { useToast } from "@/components/Toast";
import { SkuPicker } from "@/features/integrations/pickers";
import { FULFILMENT_ROUTES } from "@/features/integrations/types";
import { type ApiError, api, apiGet } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";
import { numberCodec, useSearchParamsState } from "@/lib/useSearchParamsState";

/** Rules per page. The endpoint's own default; ~4400 rules after the 2026-10
 *  bulk import, so the unpaged list silently showed the first 200 of them. */
const RULES_PAGE_SIZE = 200;

export function SourcingPage() {
  const qc = useQueryClient();
  const toast = useToast();

  const [sku, setSku] = useState<SkuPickerRow | null>(null);
  const [mode, setMode] = useState<SourcingMode>("auto");
  const [supplierSlug, setSupplierSlug] = useState<string>("g2b");
  const [offset, setOffset] = useSearchParamsState("offset", 0, numberCodec);

  // Keyed under `qk.sourcingRules()` so the mutations below keep invalidating
  // every page with the one prefix they already use.
  const rulesQuery = useQuery<SourcingRuleListOut>({
    queryKey: [...qk.sourcingRules(), offset],
    queryFn: () =>
      apiGet<SourcingRuleListOut>(
        `/api/v1/admin/sourcing/rules?limit=${String(RULES_PAGE_SIZE)}&offset=${String(offset)}`,
      ),
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
  //
  // The rules list is paged now, so the row is only on hand when it sits on
  // the page the operator is looking at; for every other SKU the per-SKU
  // decision carries the same facts — `rule_present` plus a `strict` route
  // is exactly an explicit rule, and `primary` names its mode. Prefer the
  // row when it is here (it is the exact record); fall back to the decision
  // otherwise, so a rule on page 12 still reads as "editing", not "creating".
  const existingRule = useMemo<ExistingRule | null>(() => {
    if (!sku) return null;
    const onPage = rulesQuery.data?.items.find((r) => r.sku_id === sku.id);
    if (onPage) return { mode: onPage.mode, supplier_slug: onPage.supplier_slug };
    return ruleFromDecision(decisionQuery.data);
  }, [sku, rulesQuery.data, decisionQuery.data]);

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
    // Primitive deps on purpose: `existingRule` is rebuilt whenever either
    // query refetches (window focus, an invalidation after save), and a fresh
    // object with the same facts must not wipe an edit in progress.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sku?.id, existingRule?.mode, existingRule?.supplier_slug]);

  // `unknown`, not `SourcingRuleOut | unknown` (which collapses to
  // `unknown` anyway and eslint rightly rejects): the DELETE branch below
  // returns no body, so the two arms genuinely disagree and `onSuccess`
  // narrows for the one that does.
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
    onSuccess: (data) => {
      toast.success(
        mode === "auto" ? "Сброшено в авто" : formatSwitchSuccess(data as SourcingRuleOut),
      );
      void qc.invalidateQueries({ queryKey: qk.sourcingRules() });
      void qc.invalidateQueries({ queryKey: qk.sourcingDecision(sku?.id ?? "") });
      // The cost basis may have just moved, so anything priced off it is stale.
      void qc.invalidateQueries({ queryKey: ["admin", "sourcing", "brand"] });
      void qc.invalidateQueries({ queryKey: ["admin", "catalog", "skus"] });
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
        <Pagination
          total={rulesQuery.data?.total ?? 0}
          limit={RULES_PAGE_SIZE}
          offset={offset}
          onPageChange={setOffset}
        />
      </section>
    </div>
  );
}

/** The two facts the editor needs about a SKU's existing rule — enough to
 *  pre-fill the form and word the banner/button as "replace", from either
 *  the listed row or the per-SKU decision. */
interface ExistingRule {
  mode: SourcingMode;
  supplier_slug: string | null;
}

/** Read an explicit rule back out of the per-SKU decision.
 *
 * Mirrors `_resolve_explicit_rule` in `sourcing/service.py`: an explicit
 * rule always answers `strict` with `rule_present`, and `primary` is
 * `inventory` (force_inventory), `supplier:manual` (manual) or
 * `supplier:<slug>` (force_supplier). A non-strict decision with
 * `rule_present` is a stray `mode="auto"` row — no override to edit, so
 * `null`, same as no rule at all. The one reading this cannot tell apart is
 * such a stray auto row on an unmapped top-up (auto also answers a strict
 * `supplier:manual` there); the listed row wins whenever it is on the page,
 * and the save still writes exactly what the operator picks. */
function ruleFromDecision(decision: SourcingDecisionOut | undefined): ExistingRule | null {
  if (!decision?.rule_present || !decision.strict) return null;
  if (decision.primary === "inventory") return { mode: "force_inventory", supplier_slug: null };
  if (decision.primary === "supplier:manual") return { mode: "manual", supplier_slug: null };
  const slug = decision.primary.startsWith("supplier:") ? decision.primary.slice(9) : "";
  if (!slug) return null;
  return { mode: "force_supplier", supplier_slug: slug };
}

/** What a route switch did to the money, in one line.
 *
 * A switch that only said "saved" was the whole problem this reports on: the
 * cost basis moves to the new supplier in the same request, and whether the
 * shelf price followed is the part an operator needs to see. Mirrors
 * `formatSaveSuccess` in `MappingEditPage`, which does the same job for the
 * other write that touches cost.
 */
function formatSwitchSuccess(rule: SourcingRuleOut | null | undefined): string {
  const cs = rule?.cost_sync ?? null;
  if (!cs) return "Правило сохранено";
  if (cs.updated && cs.new_cost) {
    const cost =
      cs.old_cost && cs.old_cost !== cs.new_cost
        ? `$${cs.old_cost} → $${cs.new_cost}`
        : `$${cs.new_cost}`;
    if (cs.price_drop_blocked) {
      return `Правило сохранено · себестоимость ${cost}, цена не снижена — маржа выросла`;
    }
    if (cs.new_price) {
      return `Правило сохранено · себестоимость ${cost}, цена → $${cs.new_price}`;
    }
    return `Правило сохранено · себестоимость ${cost}`;
  }
  if (cs.reason) return `Правило сохранено · себестоимость не обновлена (${cs.reason})`;
  return "Правило сохранено";
}
