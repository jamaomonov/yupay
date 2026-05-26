/** Upsert form for a single ``(sku_id, supplier_slug)`` mapping.
 *
 * Two access paths:
 *  - ``/integrations/mappings/new`` — admin picks SKU + supplier + kind + ext id.
 *  - ``/integrations/mappings/:supplier/:sku/edit`` — pre-filled from the
 *    existing row; supplier + SKU are locked.
 *
 * ``external_product_id`` gets an autocomplete suggestion list from the
 * cached supplier catalog (``supplier_catalog_cache`` is populated by the
 * sync action on the detail page). Operators can ignore the dropdown
 * entirely — typing an unknown id is allowed because the cache may be
 * stale or empty. */

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useEffect, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import { z } from "zod";

import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";
import { ApiError, apiGet, api } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import { KNOWN_SUPPLIERS, type CatalogListOut, type SupplierMapping } from "./types";

const formSchema = z
  .object({
    sku_id: z.string().uuid("Нужен UUID существующего SKU"),
    supplier_slug: z.enum(KNOWN_SUPPLIERS),
    kind: z.enum(["voucher", "game"]),
    external_product_id: z.string().min(1, "Обязательное поле").max(128),
    external_variant_id: z.string().max(128).optional().or(z.literal("")),
    quantity: z.coerce.number().int().min(1).max(10_000),
    extra_json: z.string(),
    is_active: z.boolean(),
  })
  .refine((v) => v.kind !== "game" || (v.external_variant_id ?? "").trim().length > 0, {
    message: "Для kind=game обязателен external_variant_id (catalogue_name)",
    path: ["external_variant_id"],
  })
  .refine(
    (v) => {
      if (v.extra_json.trim() === "") return true;
      try {
        const parsed: unknown = JSON.parse(v.extra_json);
        return typeof parsed === "object" && parsed !== null && !Array.isArray(parsed);
      } catch {
        return false;
      }
    },
    { message: "Должен быть JSON-объект", path: ["extra_json"] },
  );

type FormValues = z.infer<typeof formSchema>;

export function MappingEditPage() {
  const params = useParams<{ supplier?: string; sku?: string }>();
  const editing = Boolean(params.supplier && params.sku);
  const supplierSlug = params.supplier ?? "g2b";
  const navigate = useNavigate();
  const toast = useToast();

  const existing = useQuery<SupplierMapping>({
    queryKey: qk.integrationMapping(params.sku ?? "", supplierSlug),
    queryFn: async () => {
      // Backend has no GET single endpoint — we list & narrow.
      const list = await apiGet<{ items: SupplierMapping[] }>(
        `/api/v1/admin/integrations/mappings?sku_id=${params.sku ?? ""}&supplier_slug=${supplierSlug}`,
      );
      const row = list.items.find(
        (m) => m.sku_id === params.sku && m.supplier_slug === supplierSlug,
      );
      if (!row) throw new ApiError(404, "Not Found", { detail: "Маппинг не найден" });
      return row;
    },
    enabled: editing,
  });

  const form = useForm<FormValues>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      sku_id: params.sku ?? "",
      supplier_slug: (supplierSlug as (typeof KNOWN_SUPPLIERS)[number]) ?? "g2b",
      kind: "voucher",
      external_product_id: "",
      external_variant_id: "",
      quantity: 1,
      extra_json: "",
      is_active: true,
    },
  });

  useEffect(() => {
    if (!existing.data) return;
    form.reset({
      sku_id: existing.data.sku_id,
      supplier_slug: existing.data.supplier_slug as (typeof KNOWN_SUPPLIERS)[number],
      kind: existing.data.kind,
      external_product_id: existing.data.external_product_id,
      external_variant_id: existing.data.external_variant_id ?? "",
      quantity: existing.data.quantity,
      extra_json:
        Object.keys(existing.data.extra).length === 0
          ? ""
          : JSON.stringify(existing.data.extra, null, 2),
      is_active: existing.data.is_active,
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing.data]);

  const watchedSupplier = form.watch("supplier_slug");
  const watchedKind = form.watch("kind");

  const [submitError, setSubmitError] = useState<string | null>(null);

  const onSubmit = form.handleSubmit(async (values) => {
    setSubmitError(null);
    const payload = {
      supplier_slug: values.supplier_slug,
      kind: values.kind,
      external_product_id: values.external_product_id.trim(),
      external_variant_id:
        values.external_variant_id && values.external_variant_id.trim() !== ""
          ? values.external_variant_id.trim()
          : null,
      quantity: values.quantity,
      extra: values.extra_json.trim() === "" ? {} : (JSON.parse(values.extra_json) as unknown),
      is_active: values.is_active,
    };
    try {
      await api<SupplierMapping>(`/api/v1/admin/integrations/mappings/${values.sku_id}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      toast.success("Маппинг сохранён");
      navigate(`/integrations/mappings?supplier=${values.supplier_slug}`);
    } catch (err) {
      const msg = formatError(err);
      setSubmitError(msg);
      toast.error(`Не удалось сохранить: ${msg}`);
    }
  });

  return (
    <form onSubmit={onSubmit}>
      <PageHeader
        title={editing ? "Изменить маппинг" : "Создать маппинг"}
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
            <Button type="submit" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? "Сохранение…" : "Сохранить"}
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="space-y-4 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
          <Field label="SKU ID (UUID)" error={form.formState.errors.sku_id?.message}>
            <Input
              {...form.register("sku_id")}
              placeholder="018f-…"
              disabled={editing}
              className="font-mono"
            />
          </Field>
          <Field label="Поставщик" error={form.formState.errors.supplier_slug?.message}>
            <select
              {...form.register("supplier_slug")}
              disabled={editing}
              className="flex h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm disabled:opacity-50"
            >
              {KNOWN_SUPPLIERS.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Тип" error={form.formState.errors.kind?.message}>
            <div className="flex gap-3">
              <label className="flex items-center gap-2 text-sm">
                <input type="radio" value="voucher" {...form.register("kind")} />
                Ваучер (одноразовый код)
              </label>
              <label className="flex items-center gap-2 text-sm">
                <input type="radio" value="game" {...form.register("kind")} />
                Игровой топ-ап
              </label>
            </div>
          </Field>
          <div className="flex gap-4">
            <Field label="Множитель" error={form.formState.errors.quantity?.message}>
              <Input
                type="number"
                min={1}
                max={10_000}
                {...form.register("quantity")}
                className="w-24"
              />
            </Field>
            <label className="mt-6 flex items-center gap-2 text-sm">
              <input type="checkbox" {...form.register("is_active")} />
              Активен
            </label>
          </div>
        </section>

        <section className="space-y-4 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
          <Field
            label={watchedKind === "voucher" ? "Product ID у G2B" : "Game code у G2B"}
            error={form.formState.errors.external_product_id?.message}
          >
            <Controller
              control={form.control}
              name="external_product_id"
              render={({ field }) => (
                <CatalogPicker
                  supplier={watchedSupplier}
                  kind={watchedKind}
                  value={field.value}
                  onChange={field.onChange}
                />
              )}
            />
          </Field>
          {watchedKind === "game" && (
            <Field
              label="Catalogue name (например '60 UC')"
              error={form.formState.errors.external_variant_id?.message}
            >
              <Input {...form.register("external_variant_id")} placeholder="60 UC" />
            </Field>
          )}
          <Field label="Extra JSON (опционально)" error={form.formState.errors.extra_json?.message}>
            <textarea
              {...form.register("extra_json")}
              className="min-h-24 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 font-mono text-xs"
              placeholder='{"required_fields": ["player_id", "server_id"]}'
            />
          </Field>
        </section>
      </div>

      {submitError && <p className="mt-4 text-sm text-[var(--danger)]">{submitError}</p>}
    </form>
  );
}

function CatalogPicker({
  supplier,
  kind,
  value,
  onChange,
}: {
  supplier: string;
  kind: "voucher" | "game";
  value: string;
  onChange: (v: string) => void;
}) {
  const [search, setSearch] = useState("");
  const query = useQuery<CatalogListOut>({
    queryKey: qk.integrationCatalog({ supplierSlug: supplier, kind, search }),
    queryFn: () => {
      const params = new URLSearchParams({ supplier_slug: supplier, kind, limit: "20" });
      if (search.trim()) params.set("search", search.trim());
      return apiGet<CatalogListOut>(`/api/v1/admin/integrations/catalog?${params.toString()}`);
    },
    staleTime: 60_000,
  });

  return (
    <div className="space-y-2">
      <Input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
        }}
        placeholder={kind === "voucher" ? "42" : "pubg_mobile"}
        className="font-mono"
      />
      <details>
        <summary className="cursor-pointer text-xs text-[var(--text-secondary)]">
          Выбрать из кэша каталога {query.data ? `(${query.data.items.length.toString()})` : ""}
        </summary>
        <div className="mt-2 space-y-1">
          <Input
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
            }}
            placeholder="Поиск по названию…"
            className="h-8 text-xs"
          />
          <ul className="max-h-48 overflow-y-auto rounded-md border border-[var(--border-default)]">
            {query.data?.items.length === 0 && (
              <li className="px-3 py-2 text-xs text-[var(--text-tertiary)]">
                Кэш пуст — дёрни «Синхронизировать каталог» на странице поставщика.
              </li>
            )}
            {query.data?.items.map((it) => (
              <li key={`${it.kind}-${it.external_id}`}>
                <button
                  type="button"
                  onClick={() => {
                    onChange(it.external_id);
                  }}
                  className={`flex w-full items-center justify-between gap-3 px-3 py-1.5 text-left text-xs hover:bg-[var(--bg-muted)] ${
                    value === it.external_id ? "bg-[var(--bg-accent-soft)]" : ""
                  }`}
                >
                  <span className="truncate">{it.title}</span>
                  <code className="shrink-0 text-[10px] text-[var(--text-tertiary)]">
                    {it.external_id}
                  </code>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </details>
    </div>
  );
}

function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string | undefined;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium uppercase text-[var(--text-secondary)]">{label}</span>
      <div className="mt-1">{children}</div>
      {error && <span className="mt-1 block text-xs text-[var(--danger)]">{error}</span>}
    </label>
  );
}

function formatError(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string; title?: string } | null;
    return body?.detail ?? body?.title ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "неизвестная ошибка";
}
