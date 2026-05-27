/** Mapping editor — wizard-style progressive disclosure.
 *
 * Five logical steps, all visible on one page but only "active" one at a
 * time. Earlier steps stay editable but collapse to a one-line summary
 * once filled. The intent: never make the operator scan through
 * irrelevant fields, but never lock them out of going back either.
 *
 *   1. SKU            — Combobox sourced from /admin/catalog/skus/search.
 *   2. Тип            — voucher | game (radio chips).
 *   3. Продукт / Игра — Combobox over supplier_catalog_cache.
 *   4. Номинал        — game-only; lazy fetch of /games/{code}/catalogue.
 *      Required-fields hint + optional player checker live in this step.
 *   5. Параметры      — quantity, активность, опц. extra JSON.
 */

import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { Check, CircleDot, ShoppingCart, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";
import { ApiError, api, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import { DenomPicker, PlayerChecker, RequiredFieldsHint } from "./gameWidgets";
import { CatalogPicker, SkuPicker } from "./pickers";
import type {
  CatalogEntry,
  MappingKind,
  SkuPickerRow,
  SupplierMapping,
  SupplierMappingUpsertResult,
} from "./types";

const SUPPLIER_SLUG = "g2b";

interface ExistingMappingPayload {
  items: SupplierMapping[];
}

export function MappingEditPage() {
  const params = useParams<{ supplier?: string; sku?: string }>();
  const editing = Boolean(params.supplier && params.sku);
  const navigate = useNavigate();
  const toast = useToast();

  // ---- form state ----
  const [sku, setSku] = useState<SkuPickerRow | null>(null);
  const [kind, setKind] = useState<MappingKind | null>(null);
  const [catalog, setCatalog] = useState<CatalogEntry | null>(null);
  const [denom, setDenom] = useState<string>("");
  const [quantity, setQuantity] = useState(1);
  const [isActive, setIsActive] = useState(true);
  const [extraJson, setExtraJson] = useState("");
  const [submitError, setSubmitError] = useState<string | null>(null);

  // ---- prefill from existing mapping ----
  const existing = useQuery<SupplierMapping | null>({
    queryKey: qk.integrationMapping(params.sku ?? "", params.supplier ?? ""),
    queryFn: async () => {
      const list = await apiGet<ExistingMappingPayload>(
        `/api/v1/admin/integrations/mappings?sku_id=${params.sku ?? ""}&supplier_slug=${params.supplier ?? ""}`,
      );
      return (
        list.items.find((m) => m.sku_id === params.sku && m.supplier_slug === params.supplier) ??
        null
      );
    },
    enabled: editing,
  });

  // SKU prefill needs a second query because the mapping row has only the
  // sku_id, not the full picker row.
  const existingSkuQuery = useQuery<SkuPickerRow[]>({
    queryKey: ["admin", "catalog", "skus", "single", params.sku ?? ""] as const,
    queryFn: () => apiGet<SkuPickerRow[]>(`/api/v1/admin/catalog/skus/search`),
    enabled: editing,
  });

  useEffect(() => {
    if (!existing.data) return;
    setKind(existing.data.kind);
    setQuantity(existing.data.quantity);
    setIsActive(existing.data.is_active);
    setDenom(existing.data.external_variant_id ?? "");
    setExtraJson(
      Object.keys(existing.data.extra).length === 0
        ? ""
        : JSON.stringify(existing.data.extra, null, 2),
    );
    // catalog prefill — synthesise a minimal CatalogEntry from the row.
    setCatalog({
      supplier_slug: existing.data.supplier_slug,
      kind: existing.data.kind === "voucher" ? "voucher" : "game",
      external_id: existing.data.external_product_id,
      title: existing.data.external_product_id,
      raw: {},
      fetched_at: new Date().toISOString(),
    });
  }, [existing.data]);

  useEffect(() => {
    if (!existingSkuQuery.data || !params.sku) return;
    const found = existingSkuQuery.data.find((s) => s.id === params.sku);
    if (found) setSku(found);
  }, [existingSkuQuery.data, params.sku]);

  // ---- derived completeness ----
  const stepStatus = useMemo(() => {
    const s1 = Boolean(sku);
    const s2 = Boolean(kind);
    const s3 = Boolean(catalog);
    const s4 = kind !== "game" || denom.trim().length > 0;
    const s5 = quantity > 0;
    return { s1, s2, s3, s4, s5, all: s1 && s2 && s3 && s4 && s5 };
  }, [sku, kind, catalog, denom, quantity]);

  // ---- save ----
  const save = useMutation<SupplierMappingUpsertResult, ApiError>({
    mutationFn: () =>
      api<SupplierMappingUpsertResult>(`/api/v1/admin/integrations/mappings/${sku?.id ?? ""}`, {
        method: "PUT",
        body: JSON.stringify({
          supplier_slug: SUPPLIER_SLUG,
          kind,
          external_product_id: catalog?.external_id ?? "",
          external_variant_id: kind === "game" && denom.trim() ? denom.trim() : null,
          quantity,
          extra: parseExtra(extraJson),
          is_active: isActive,
        }),
      }),
    onSuccess: (result) => {
      toast.success(formatSaveSuccess(result));
      navigate(`/integrations/mappings?supplier=${SUPPLIER_SLUG}`);
    },
    onError: (err) => {
      const msg = formatError(err);
      setSubmitError(msg);
      toast.error(`Не удалось сохранить: ${msg}`);
    },
  });

  const validate = (): string | null => {
    if (!sku) return "Шаг 1 не заполнен: выберите SKU";
    if (!kind) return "Шаг 2 не заполнен: выберите тип";
    if (!catalog) return "Шаг 3 не заполнен: выберите продукт или игру G2B";
    if (kind === "game" && !denom.trim()) return "Шаг 4 не заполнен: укажите номинал";
    if (quantity <= 0) return "Шаг 5: множитель должен быть положительным";
    try {
      parseExtra(extraJson);
    } catch (err) {
      return `Поле «Extra JSON»: ${(err as Error).message}`;
    }
    return null;
  };

  const onSubmit = () => {
    setSubmitError(null);
    const err = validate();
    if (err) {
      setSubmitError(err);
      return;
    }
    save.mutate();
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title={editing ? "Изменить маппинг" : "Создать маппинг"}
        description="Связь SKU с продуктом G2B. Поставщик будет выкупать у G2B заказ, когда покупатель оплачивает этот SKU."
        breadcrumbs={[
          { label: "Интеграции", to: "/integrations" },
          { label: "Маппинги", to: "/integrations/mappings" },
          { label: editing ? "Изменить" : "Создать" },
        ]}
        actions={
          <>
            <Link
              to="/integrations/mappings"
              className="inline-flex h-8 items-center rounded-md border border-[var(--border-default)] px-3 text-sm hover:bg-[var(--bg-muted)]"
            >
              Отмена
            </Link>
            <Button
              type="button"
              onClick={onSubmit}
              disabled={!stepStatus.all || save.isPending}
              variant="primary"
              size="sm"
            >
              {save.isPending ? "Сохранение…" : "Сохранить"}
            </Button>
          </>
        }
      />

      <Step
        number={1}
        title="Какой YuPay SKU вы маппите?"
        done={stepStatus.s1}
        active={!stepStatus.s1}
      >
        <SkuPicker value={sku} onChange={setSku} disabled={editing} />
        {sku && (
          <p className="mt-2 text-xs text-[var(--text-tertiary)]">
            <code className="font-mono">{sku.id}</code>
          </p>
        )}
      </Step>

      <Step
        number={2}
        title="Что это будет — ваучер или игровой топ-ап?"
        done={stepStatus.s2}
        active={stepStatus.s1 && !stepStatus.s2}
        disabled={!stepStatus.s1}
      >
        <KindPicker value={kind} onChange={setKind} skuKind={sku?.product_kind} />
      </Step>

      <Step
        number={3}
        title={
          kind === "voucher"
            ? "Какой продукт G2B соответствует SKU?"
            : kind === "game"
              ? "Какая игра G2B соответствует SKU?"
              : "Что у G2B?"
        }
        done={stepStatus.s3}
        active={stepStatus.s2 && !stepStatus.s3}
        disabled={!stepStatus.s2}
      >
        {kind && (
          <CatalogPicker
            supplier={SUPPLIER_SLUG}
            kind={kind}
            value={catalog}
            onChange={(next) => {
              setCatalog(next);
              if (next?.external_id !== catalog?.external_id) setDenom("");
            }}
          />
        )}
      </Step>

      {kind === "game" && (
        <Step
          number={4}
          title="Какой номинал из каталога игры?"
          done={stepStatus.s4}
          active={stepStatus.s3 && !stepStatus.s4}
          disabled={!stepStatus.s3}
        >
          <DenomPicker gameCode={catalog?.external_id ?? null} value={denom} onChange={setDenom} />
          <div className="mt-4 space-y-3">
            <RequiredFieldsHint gameCode={catalog?.external_id ?? null} />
            <PlayerChecker gameCode={catalog?.external_id ?? null} />
          </div>
        </Step>
      )}

      <Step
        number={kind === "game" ? 5 : 4}
        title="Финальные параметры"
        done={stepStatus.s5}
        active={kind === "game" ? stepStatus.s4 && !stepStatus.s5 : stepStatus.s3 && !stepStatus.s5}
        disabled={kind === "game" ? !stepStatus.s4 : !stepStatus.s3}
      >
        <div className="flex flex-wrap items-end gap-6">
          <label className="block">
            <span className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
              Множитель
            </span>
            <input
              type="number"
              min={1}
              max={10_000}
              value={quantity}
              onChange={(e) => {
                setQuantity(Math.max(1, Number(e.target.value) || 1));
              }}
              className="mt-1 h-10 w-24 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm"
            />
            <span className="mt-1 block text-[10px] text-[var(--text-tertiary)]">
              сколько единиц у G2B = один наш SKU
            </span>
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => {
                setIsActive(e.target.checked);
              }}
            />
            Активен
          </label>
        </div>
        <details className="mt-4">
          <summary className="cursor-pointer text-xs text-[var(--text-tertiary)]">
            Extra JSON (опционально)
          </summary>
          <textarea
            value={extraJson}
            onChange={(e) => {
              setExtraJson(e.target.value);
            }}
            className="mt-2 min-h-24 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 font-mono text-xs"
            placeholder='{"notes": "free-form metadata"}'
          />
        </details>
      </Step>

      {submitError && (
        <div
          role="alert"
          className="rounded-md border border-[var(--danger)] bg-[var(--bg-muted)] px-4 py-3 text-sm text-[var(--danger)]"
        >
          {submitError}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step shell
// ---------------------------------------------------------------------------

function Step({
  number,
  title,
  done,
  active,
  disabled,
  children,
}: {
  number: number;
  title: string;
  done: boolean;
  active?: boolean | undefined;
  disabled?: boolean | undefined;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-disabled={disabled}
      className={[
        "rounded-lg border bg-[var(--bg-surface)] transition-colors",
        active
          ? "border-[var(--accent)] shadow-[var(--shadow-sm)]"
          : "border-[var(--border-default)]",
        disabled ? "opacity-60" : "",
      ].join(" ")}
    >
      <header className="flex items-center justify-between gap-3 border-b border-[var(--border-subtle)] px-4 py-2.5">
        <div className="flex items-center gap-3">
          <StepBadge number={number} done={done} active={active} />
          <h2 className="text-sm font-medium">{title}</h2>
        </div>
      </header>
      <div className="px-4 py-4">{children}</div>
    </section>
  );
}

function StepBadge({
  number,
  done,
  active,
}: {
  number: number;
  done: boolean;
  active?: boolean | undefined;
}) {
  if (done) {
    return (
      <span className="flex size-6 items-center justify-center rounded-full bg-[var(--accent)] text-[var(--text-on-accent)]">
        <Check className="size-3.5" aria-hidden />
      </span>
    );
  }
  if (active) {
    return (
      <span className="flex size-6 items-center justify-center rounded-full border border-[var(--accent)] text-[var(--accent)]">
        <CircleDot className="size-3.5" aria-hidden />
      </span>
    );
  }
  return (
    <span className="flex size-6 items-center justify-center rounded-full border border-[var(--border-default)] text-xs text-[var(--text-tertiary)]">
      {number.toString()}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Kind picker
// ---------------------------------------------------------------------------

function KindPicker({
  value,
  onChange,
  skuKind,
}: {
  value: MappingKind | null;
  onChange: (next: MappingKind) => void;
  skuKind: string | undefined;
}) {
  // Hint when the YuPay product type doesn't match the obvious G2B branch.
  const recommended: MappingKind | null =
    skuKind === "top_up" ? "game" : skuKind === "voucher" ? "voucher" : null;

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <KindCard
          icon={ShoppingCart}
          label="Ваучер"
          description="Одноразовый код (gift card, PSN, Steam). G2B возвращает строку — мы кладём её в delivery."
          selected={value === "voucher"}
          recommended={recommended === "voucher"}
          onSelect={() => {
            onChange("voucher");
          }}
        />
        <KindCard
          icon={Sparkles}
          label="Игровой топ-ап"
          description="Прямое начисление в игре (PUBG UC, MLBB Diamonds). Клиент вводит player_id при покупке."
          selected={value === "game"}
          recommended={recommended === "game"}
          onSelect={() => {
            onChange("game");
          }}
        />
      </div>
      {recommended && skuKind && (
        <p className="text-xs text-[var(--text-tertiary)]">
          SKU помечен как <code className="font-mono">{skuKind}</code> — обычно это{" "}
          <strong>{recommended === "game" ? "игровой топ-ап" : "ваучер"}</strong>.
        </p>
      )}
    </div>
  );
}

function KindCard({
  icon: Icon,
  label,
  description,
  selected,
  recommended,
  onSelect,
}: {
  icon: typeof ShoppingCart;
  label: string;
  description: string;
  selected: boolean;
  recommended?: boolean | undefined;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={[
        "flex flex-col items-start gap-2 rounded-md border p-4 text-left transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-base)]",
        selected
          ? "border-[var(--accent)] bg-[var(--bg-accent-soft)]"
          : "border-[var(--border-default)] hover:bg-[var(--bg-muted)]",
      ].join(" ")}
    >
      <div className="flex w-full items-center justify-between gap-3">
        <Icon className="size-5 text-[var(--accent)]" aria-hidden />
        {recommended && (
          <span className="rounded-full bg-[var(--bg-muted)] px-2 py-0.5 text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">
            рекомендуем
          </span>
        )}
      </div>
      <span className="font-medium">{label}</span>
      <span className="text-xs text-[var(--text-secondary)]">{description}</span>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseExtra(raw: string): Record<string, unknown> {
  const trimmed = raw.trim();
  if (trimmed === "") return {};
  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed);
  } catch (err) {
    throw new Error(`невалидный JSON: ${(err as Error).message}`);
  }
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("должен быть JSON-объект");
  }
  return parsed as Record<string, unknown>;
}

function formatSaveSuccess(result: SupplierMappingUpsertResult): string {
  const cs = result.cost_sync;
  if (cs.updated && cs.new_cost) {
    const arrow =
      cs.old_cost && cs.old_cost !== cs.new_cost
        ? `$${cs.old_cost} → $${cs.new_cost}`
        : `$${cs.new_cost}`;
    return `Маппинг сохранён · себестоимость ${arrow}`;
  }
  if (!cs.updated && cs.reason) {
    return `Маппинг сохранён · cost_usdt не обновлён (${cs.reason})`;
  }
  return "Маппинг сохранён";
}

function formatError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string; title?: string } | null;
    return body?.detail ?? body?.title ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "неизвестная ошибка";
}
