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

import { BrandSourcingTable } from "./BrandSourcingTable";
import { switchSkusChunked } from "./bulkSwitch";

import type { SourcingBrandOverviewOut, SourcingBulkRuleOut, SourcingMode } from "./types";
import type { Brand } from "@/features/catalog/types";

import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";
import { FULFILMENT_ROUTES } from "@/features/integrations/types";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

// Same candidate list `SourcingPage` offers for `force_supplier` — derived
// from the shared route table so a newly integrated supplier shows up here
// without a second edit. Reserve suppliers (NOVA) are included: reaching
// one is exactly what an explicit `force_supplier` choice is for
// (`RESERVE_SUPPLIERS`, ADR-0081) — what must never happen is offering one
// as the outcome of `mode: "auto"`, which this list is never used for.
const SUPPLIER_OPTIONS = FULFILMENT_ROUTES.filter((r) => r.external || r.slug === "mock");

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
    },
    onError: () => {
      toast.error("Не удалось выполнить переключение.");
    },
  });

  const switchOne = (skuId: string, mode: SourcingMode, supplierSlug: string | null) => {
    setFailures(new Map());
    switchSkusChunked([skuId], mode, supplierSlug)
      .then((result) => {
        const item = result.items[0];
        if (item?.ok) {
          toast.success(`${skuCodeFor(skuId)}: переключено`);
        } else {
          toast.error(`${skuCodeFor(skuId)}: ${item?.error ?? "не удалось переключить"}`);
          setFailures(new Map([[skuId, item?.error ?? "не удалось переключить"]]));
        }
        void qc.invalidateQueries({ queryKey: qk.sourcingBrandOverview(brandSlug ?? "") });
      })
      .catch(() => {
        toast.error(`${skuCodeFor(skuId)}: не удалось переключить`);
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
          <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
            Бренд
          </label>
          <Select
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
              <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
                Режим для {selected.size.toString()} SKU
              </label>
              <Select
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
                <label className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-tertiary)]">
                  Поставщик
                </label>
                <Select
                  value={bulkSupplier}
                  onChange={(e) => {
                    setBulkSupplier(e.target.value);
                  }}
                  containerClassName="w-40"
                >
                  {SUPPLIER_OPTIONS.map((s) => (
                    <option key={s.slug} value={s.slug}>
                      {s.label}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            <Button
              onClick={() => {
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
          failures={failures}
        />
      )}
    </div>
  );
}
