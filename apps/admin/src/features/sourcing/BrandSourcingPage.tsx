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
import { Button, Select } from "@yupay/ui";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { supplierLabel } from "./brandSourcingFormat";
import { BrandSourcingTable } from "./BrandSourcingTable";
import { switchSkusChunked } from "./bulkSwitch";
import { BULK_SUPPLIER_OPTIONS } from "./supplierOptions";

import type { SourcingBrandOverviewOut, SourcingBulkRuleOut, SourcingMode } from "./types";
import type { Brand } from "@/features/catalog/types";

import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";
import { RESERVE_SUPPLIERS } from "@/features/integrations/types";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

// Human name for each bulk mode, used only in the confirmation prompt below
// — the <option> labels stay inline since they're rendered once each and
// never reused elsewhere.
const BULK_MODE_CONFIRM_LABELS: Record<SourcingMode, string> = {
  force_supplier: "поставщика",
  force_inventory: "режим «Только склад»",
  manual: "режим «Вручную»",
  auto: "режим «Авто»",
};

function brandName(b: Brand): string {
  return b.translations.find((t) => t.locale === "ru")?.name ?? b.slug;
}

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
    mutationFn: ({ skuIds }) =>
      switchSkusChunked(skuIds, bulkMode, bulkMode === "force_supplier" ? bulkSupplier : null),
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
  // bigger (up to hundreds of SKUs) and had no confirmation at all.
  const confirmBulkApply = (): boolean => {
    const target =
      bulkMode === "force_supplier"
        ? `поставщика ${supplierLabel(bulkSupplier)}`
        : BULK_MODE_CONFIRM_LABELS[bulkMode];
    return window.confirm(`Переключить ${selected.size.toString()} SKU на ${target}?`);
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

      <section className="flex flex-wrap items-end gap-4 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
        <div>
          <label
            htmlFor="brand-sourcing-brand-select"
            className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]"
          >
            Бренд
          </label>
          <Select
            id="brand-sourcing-brand-select"
            value={brandSlug ?? ""}
            onChange={(e) => {
              const slug = e.target.value;
              void navigate(slug ? `/sourcing/brands/${slug}` : "/sourcing/brands");
              setSelected(new Set());
              setFailures(new Map());
            }}
            containerClassName="w-64"
          >
            <option value="">— Выбери бренд —</option>
            {brandsQuery.data?.map((b) => (
              <option key={b.id} value={b.slug}>
                {brandName(b)}
              </option>
            ))}
          </Select>
        </div>

        {selected.size > 0 && (
          <>
            <div>
              <label
                htmlFor="brand-sourcing-mode-select"
                className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]"
              >
                Режим для {selected.size.toString()} SKU
              </label>
              <Select
                id="brand-sourcing-mode-select"
                value={bulkMode}
                onChange={(e) => {
                  // Narrowing a DOM value: every <option> below is a literal
                  // SourcingMode, so the select can never produce anything else.
                  setBulkMode(e.target.value as SourcingMode);
                }}
                containerClassName="w-48"
              >
                <option value="force_supplier">Только поставщик</option>
                <option value="force_inventory">Только склад</option>
                <option value="manual">Вручную</option>
                <option value="auto">Авто</option>
              </Select>
            </div>
            {bulkMode === "force_supplier" && (
              <div>
                <label
                  htmlFor="brand-sourcing-supplier-select"
                  className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]"
                >
                  Поставщик
                </label>
                <Select
                  id="brand-sourcing-supplier-select"
                  value={bulkSupplier}
                  onChange={(e) => {
                    setBulkSupplier(e.target.value);
                  }}
                  containerClassName="w-40"
                >
                  {BULK_SUPPLIER_OPTIONS.map((s) => (
                    <option key={s.slug} value={s.slug}>
                      {s.label}
                      {RESERVE_SUPPLIERS.has(s.slug) ? " · резерв" : ""}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <Button
              onClick={() => {
                if (!confirmBulkApply()) return;
                switchMutation.mutate({ skuIds: [...selected] });
              }}
              disabled={!canApply}
            >
              {switchMutation.isPending
                ? "Переключаем…"
                : `Применить к ${selected.size.toString()}`}
            </Button>
          </>
        )}
      </section>

      {brandSlug === null ? (
        <p className="text-sm text-[var(--text-secondary)]">Выбери бренд, чтобы увидеть SKU.</p>
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
        />
      )}
    </div>
  );
}
