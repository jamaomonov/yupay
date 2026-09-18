/** Sourcing by brand — compare suppliers and switch many SKUs at once.
 *
 * The one-SKU-at-a-time editor (`SourcingPage`) cannot answer "who is
 * cheaper for this SKU", because nothing on that screen shows a cost
 * comparison, and switching a whole brand meant editing every SKU by hand
 * (see `docs/superpowers/specs/2026-09-18-sourcing-by-brand-design.md`
 * §6). This screen replaces that for the brand-level job; the single-SKU
 * editor stays reachable for a one-off edit.
 *
 * Every write — the header bulk action and each row's own controls —
 * goes through the same `switchSkusChunked` helper (`./bulkSwitch.ts`),
 * so there is exactly one place that chunks an oversized selection and
 * mints Idempotency-Keys. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import {
  bulkConfirmMessage,
  FORCE_INVENTORY_TOPUP_ERROR,
  inventoryRoutedCount,
  partitionForceInventorySelection,
} from "./brandSourcingFormat";
import { BrandSourcingTable } from "./BrandSourcingTable";
import { BrandSourcingToolbar } from "./BrandSourcingToolbar";
import { switchSkusChunked } from "./bulkSwitch";

import type { SourcingBrandOverviewOut, SourcingBulkRuleOut, SourcingMode } from "./types";
import type { Brand } from "@/features/catalog/types";

import { PageHeader } from "@/components/PageHeader";
import { ErrorState } from "@/components/States";
import { useToast } from "@/components/Toast";
import { apiGet } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

export function BrandSourcingPage() {
  const params = useParams<{ brandSlug?: string }>();
  const brandSlug = params.brandSlug ?? null;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [bulkMode, setBulkMode] = useState<SourcingMode>("force_supplier");
  const [bulkSupplier, setBulkSupplier] = useState<string>("g2b");
  const [failures, setFailures] = useState<ReadonlyMap<string, string>>(new Map());
  // SKU ids with their own per-row switch in flight — independent of
  // `switchMutation.isPending`, which only tracks the header's bulk action.
  // Without this a per-row control stayed clickable for the whole time its
  // own write was in flight, inviting a double-submit.
  const [rowPending, setRowPending] = useState<ReadonlySet<string>>(new Set());
  // SKUs whose sourcing rule just changed successfully in this browser
  // session. `PUT .../rules:bulk` only writes `sku_sourcing_rules` —
  // `Sku.cost_usdt` (and the margin the table derives from it) is repriced
  // by the hourly job, not by the switch itself, so until that job runs the
  // table would otherwise show the new route beside the old supplier's cost
  // with nothing saying so (whole-branch review, Important #4). Cleared
  // only when the brand changes — there is no reliable client-side signal
  // for "the hourly job has now run for this SKU", so this errs toward
  // saying "not updated yet" a little longer rather than clearing early and
  // showing a stale number as current.
  const [staleCostSkuIds, setStaleCostSkuIds] = useState<ReadonlySet<string>>(new Set());

  const brandsQuery = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });

  const overviewQuery = useQuery<SourcingBrandOverviewOut>({
    queryKey: qk.sourcingBrandOverview(brandSlug ?? ""),
    queryFn: () =>
      apiGet<SourcingBrandOverviewOut>(`/api/v1/admin/sourcing/brands/${brandSlug ?? ""}`),
    enabled: brandSlug !== null,
  });

  const items = useMemo(() => overviewQuery.data?.items ?? [], [overviewQuery.data]);
  const skuCodeFor = useMemo(() => {
    const map = new Map(items.map((i) => [i.sku_id, i.sku_code]));
    return (skuId: string) => map.get(skuId) ?? skuId;
  }, [items]);

  const switchMutation = useMutation<SourcingBulkRuleOut, unknown, { skuIds: string[] }>({
    // `force_inventory` needs one extra step the other modes don't: a
    // ticked selection can mix top_up and voucher rows, and the backend
    // rejects the mode outright for a top_up SKU (the code warehouse has
    // nothing to issue for one). Neither dropping the top-ups silently
    // (they'd look switched when nothing was ever sent for them) nor
    // blocking the whole action (the voucher rows are a legitimate,
    // independent switch) is right — split the selection, send only what
    // can apply, and report the rest the same way a real per-SKU
    // rejection already renders (`onSuccess` below treats every entry in
    // `data.items` alike, real or synthesized). `switchSkusChunked` makes
    // no network call for an empty `applicable` list (its chunk loop
    // never runs), so an all-top_up selection resolves locally.
    mutationFn: async ({ skuIds }) => {
      if (bulkMode !== "force_inventory") {
        return switchSkusChunked(
          skuIds,
          bulkMode,
          bulkMode === "force_supplier" ? bulkSupplier : null,
        );
      }
      const { applicable, blocked } = partitionForceInventorySelection(items, new Set(skuIds));
      const result = await switchSkusChunked(applicable, bulkMode, null);
      return {
        items: [
          ...result.items,
          ...blocked.map((skuId) => ({
            sku_id: skuId,
            ok: false,
            error: FORCE_INVENTORY_TOPUP_ERROR,
          })),
        ],
      };
    },
    onSuccess: (data) => {
      const failed = data.items.filter((i) => !i.ok);
      const okCount = data.items.length - failed.length;
      setFailures(new Map(failed.map((f) => [f.sku_id, f.error ?? "неизвестная ошибка"])));
      if (failed.length === 0) {
        toast.success(`Переключено: ${okCount.toString()}`);
      } else {
        toast.error(
          `Переключено ${okCount.toString()} из ${data.items.length.toString()} — ` +
            `${failed.length.toString()} с ошибкой`,
        );
      }
      // Keep the failed ids ticked so the operator can fix and retry; drop
      // the ones that succeeded.
      setSelected((prev) => {
        const next = new Set(prev);
        for (const item of data.items) if (item.ok) next.delete(item.sku_id);
        return next;
      });
      setStaleCostSkuIds((prev) => {
        const next = new Set(prev);
        for (const item of data.items) if (item.ok) next.add(item.sku_id);
        return next;
      });
      void qc.invalidateQueries({ queryKey: qk.sourcingBrandOverview(brandSlug ?? "") });
      // The single-SKU editor's explicit-rules table reads this key —
      // without invalidating it too, a bulk switch here can leave that
      // table showing a stale rule after the operator navigates back.
      void qc.invalidateQueries({ queryKey: qk.sourcingRules() });
    },
    onError: () => {
      toast.error("Не удалось выполнить переключение.");
    },
  });

  const switchOne = (skuId: string, mode: SourcingMode, supplierSlug: string | null) => {
    // Merge into the existing failures map — replacing it wholesale would
    // wipe every other row's still-current failure reason from the last
    // bulk apply the moment this one row's quick action fires, right as
    // the operator is retrying exactly one of several failed rows.
    setFailures((prev) => {
      const next = new Map(prev);
      next.delete(skuId);
      return next;
    });
    setRowPending((prev) => new Set(prev).add(skuId));
    switchSkusChunked([skuId], mode, supplierSlug)
      .then((result) => {
        const item = result.items[0];
        if (item?.ok) {
          toast.success(`${skuCodeFor(skuId)}: переключено`);
          setFailures((prev) => {
            const next = new Map(prev);
            next.delete(skuId);
            return next;
          });
          setStaleCostSkuIds((prev) => new Set(prev).add(skuId));
        } else {
          const message = item?.error ?? "не удалось переключить";
          toast.error(`${skuCodeFor(skuId)}: ${message}`);
          setFailures((prev) => new Map(prev).set(skuId, message));
        }
        void qc.invalidateQueries({ queryKey: qk.sourcingBrandOverview(brandSlug ?? "") });
        void qc.invalidateQueries({ queryKey: qk.sourcingRules() });
      })
      .catch(() => {
        const message = "не удалось переключить";
        toast.error(`${skuCodeFor(skuId)}: ${message}`);
        setFailures((prev) => new Map(prev).set(skuId, message));
      })
      .finally(() => {
        setRowPending((prev) => {
          const next = new Set(prev);
          next.delete(skuId);
          return next;
        });
      });
  };

  const toggle = (skuId: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(skuId)) next.delete(skuId);
      else next.add(skuId);
      return next;
    });
  };

  const toggleAll = () => {
    setSelected((prev) => {
      if (items.length > 0 && items.every((i) => prev.has(i.sku_id))) return new Set();
      return new Set(items.map((i) => i.sku_id));
    });
  };

  const canApply =
    selected.size > 0 &&
    !switchMutation.isPending &&
    (bulkMode !== "force_supplier" || bulkSupplier.trim().length > 0);

  // Names the count and the target — a whole brand can be re-routed from
  // this one button, and the single-rule delete elsewhere on this same
  // feature already asks before a destructive action; this action is
  // bigger (up to hundreds of SKUs) and had no confirmation at all. Also
  // names the warehouse-bypass consequence when it applies (Important #1) —
  // see `bulkConfirmMessage`.
  //
  // `force_inventory` counts its *applicable* SKUs, not the whole ticked
  // selection (whole-branch review #5): a mixed selection sends only the
  // voucher rows (`partitionForceInventorySelection`), so confirming with
  // `selected.size` would ask "Переключить 2 SKU" when only 1 is ever
  // attempted. Every other mode sends the full selection as-is, so
  // `selected.size` stays correct for them.
  const confirmBulkApply = (): boolean => {
    const count =
      bulkMode === "force_inventory"
        ? partitionForceInventorySelection(items, selected).applicable.length
        : selected.size;
    const message = bulkConfirmMessage(
      count,
      bulkMode,
      bulkSupplier,
      inventoryRoutedCount(items, selected),
    );
    return window.confirm(message);
  };

  const handleBrandChange = (slug: string) => {
    void navigate(slug ? `/sourcing/brands/${slug}` : "/sourcing/brands");
    setSelected(new Set());
    setFailures(new Map());
    setStaleCostSkuIds(new Set());
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Sourcing по бренду"
        description="Сравнение поставщиков и массовое переключение SKU одного бренда."
        breadcrumbs={[{ label: "Sourcing", to: "/sourcing" }, { label: "По бренду" }]}
        actions={
          <Link to="/sourcing" className="text-sm text-[var(--text-secondary)] hover:underline">
            ← Одиночный редактор
          </Link>
        }
      />

      <BrandSourcingToolbar
        brands={brandsQuery.data}
        brandSlug={brandSlug}
        onBrandChange={handleBrandChange}
        selectedCount={selected.size}
        bulkMode={bulkMode}
        onBulkModeChange={setBulkMode}
        bulkSupplier={bulkSupplier}
        onBulkSupplierChange={setBulkSupplier}
        canApply={canApply}
        applyPending={switchMutation.isPending}
        onApply={() => {
          if (!confirmBulkApply()) return;
          switchMutation.mutate({ skuIds: [...selected] });
        }}
      />

      {brandSlug === null ? (
        <p className="text-sm text-[var(--text-secondary)]">Выбери бренд, чтобы увидеть SKU.</p>
      ) : overviewQuery.isError ? (
        <ErrorState
          description={extractApiMessage(overviewQuery.error)}
          onRetry={() => void overviewQuery.refetch()}
          retryPending={overviewQuery.isFetching}
        />
      ) : (
        <BrandSourcingTable
          items={items}
          loading={overviewQuery.isLoading}
          selected={selected}
          onToggle={toggle}
          onToggleAll={toggleAll}
          onSwitchOne={switchOne}
          pending={switchMutation.isPending}
          pendingSkuIds={rowPending}
          failures={failures}
          staleCostSkuIds={staleCostSkuIds}
        />
      )}
    </div>
  );
}
