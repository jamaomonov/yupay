/** Import a single G2B game → Brand + Product + SKUs + mappings. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { DenominationTable } from "./DenominationTable";
import {
  g2bFieldLabel,
  type FormFieldDto,
  type GameDenomList,
  type GameDenomRow,
  type GameFields,
  type GameImportPayload,
  type GameImportResult,
} from "./types";

import type { Brand, Category } from "@/features/catalog/types";

import { Field } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { useToast } from "@/components/Toast";
import { apiGet, apiPost, type ApiError } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

export interface DenomState {
  checked: boolean;
  sku_code: string;
  price_override: string; // empty = use margin
}

function slugify(s: string): string {
  return s
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

export function GameImportPage() {
  const { slug = "g2b", gameCode = "" } = useParams<{ slug?: string; gameCode?: string }>();
  const code = decodeURIComponent(gameCode);
  const navigate = useNavigate();
  const toast = useToast();

  const [target, setTarget] = useState<"new_brand" | "existing_brand">("new_brand");
  const [brandId, setBrandId] = useState("");
  const [brandName, setBrandName] = useState(code);
  const [brandSlug, setBrandSlug] = useState(slugify(code));
  const [categoryId, setCategoryId] = useState("");
  const [productName, setProductName] = useState(code);
  const [productSlug, setProductSlug] = useState(slugify(`${code}-topup`));
  const [margin, setMargin] = useState("20");
  const [rows, setRows] = useState<Record<string, DenomState>>({});

  const denoms = useQuery<GameDenomList>({
    queryKey: qk.g2bGameCatalogue(code),
    queryFn: () =>
      apiGet<GameDenomList>(
        `/api/v1/admin/integrations/g2b/games/${encodeURIComponent(code)}/catalogue`,
      ),
  });
  const fields = useQuery<GameFields>({
    queryKey: qk.g2bGameFields(code),
    queryFn: () =>
      apiGet<GameFields>(`/api/v1/admin/integrations/g2b/games/${encodeURIComponent(code)}/fields`),
  });
  const categories = useQuery<Category[]>({
    queryKey: qk.categories(),
    queryFn: () => apiGet<Category[]>("/api/v1/admin/catalog/categories"),
  });
  const brands = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });

  const requiredFields: FormFieldDto[] = useMemo(
    () =>
      (fields.data?.fields ?? []).map((key) => ({
        key,
        label: g2bFieldLabel(key),
        type: "text" as const,
        required: true,
      })),
    [fields.data],
  );

  function defaultState(catalogueName: string): DenomState {
    return {
      checked: true,
      sku_code: slugify(`g2b-${code}-${catalogueName}`),
      price_override: "",
    };
  }

  function rowState(d: GameDenomRow): DenomState {
    return rows[d.catalogue_name] ?? defaultState(d.catalogue_name);
  }

  function setRow(name: string, patch: Partial<DenomState>) {
    setRows((prev) => ({
      ...prev,
      [name]: {
        ...(prev[name] ?? defaultState(name)),
        ...patch,
      },
    }));
  }

  const save = useMutation<GameImportResult, ApiError>({
    mutationFn: () => {
      const selected = (denoms.data?.items ?? []).filter((d) => rowState(d).checked && d.amount);
      const payload: GameImportPayload = {
        game_code: code,
        target,
        ...(target === "existing_brand" ? { brand_id: brandId } : {}),
        ...(target === "new_brand"
          ? { new_brand: { slug: brandSlug, category_id: categoryId, name: brandName } }
          : {}),
        product: { slug: productSlug, name: productName, required_fields: requiredFields },
        margin_percent: margin,
        denominations: selected.map((d) => {
          const st = rowState(d);
          return {
            catalogue_name: d.catalogue_name,
            denomination: d.name || d.catalogue_name,
            sku_code: st.sku_code,
            cost_usdt: String(d.amount),
            ...(st.price_override.trim() ? { price_usd_override: st.price_override.trim() } : {}),
            quantity: 1,
          };
        }),
      };
      return apiPost<GameImportResult>("/api/v1/admin/integrations/g2b/import", payload);
    },
    onSuccess: (data) => {
      toast.success(
        `Импортировано: SKU ${data.created_skus.toString()}, пропущено ${data.skipped.length.toString()}`,
      );
      void navigate(`/brands/${data.brand_id}`);
    },
    onError: (err) => {
      const body = err.body as { detail?: string; title?: string } | null;
      toast.error(`Импорт не удался: ${body?.detail ?? body?.title ?? err.message}`);
    },
  });

  const canSave =
    (target === "new_brand" ? Boolean(brandSlug && categoryId && brandName) : Boolean(brandId)) &&
    Boolean(productSlug) &&
    Boolean(productName) &&
    (denoms.data?.items ?? []).some((d) => rowState(d).checked && d.amount);

  return (
    <div>
      <PageHeader
        title={`Импорт игры · ${code}`}
        breadcrumbs={[
          { label: "Интеграции", to: "/integrations" },
          { label: "Каталог", to: `/integrations/${slug}/catalog` },
          { label: code },
        ]}
        actions={
          <Button
            onClick={() => {
              save.mutate();
            }}
            disabled={!canSave || save.isPending}
          >
            {save.isPending ? "Импортируем…" : "Импортировать"}
          </Button>
        }
      />

      {/* Step 1: destination */}
      <section className="mb-6 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4">
        <h2 className="mb-3 font-semibold">Назначение</h2>
        <div className="flex gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={target === "new_brand"}
              onChange={() => {
                setTarget("new_brand");
              }}
            />
            Новый бренд
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              checked={target === "existing_brand"}
              onChange={() => {
                setTarget("existing_brand");
              }}
            />
            Существующий бренд
          </label>
        </div>
        {target === "existing_brand" && (
          <div className="mt-3">
            <Field label="Бренд">
              {({ inputProps }) => (
                <select
                  {...inputProps}
                  value={brandId}
                  onChange={(e) => {
                    setBrandId(e.target.value);
                  }}
                  className="h-9 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm"
                >
                  <option value="">— выбери —</option>
                  {(brands.data ?? []).map((b) => (
                    <option key={b.id} value={b.id}>
                      {b.translations.find((t) => t.locale === "ru")?.name ?? b.slug}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </div>
        )}
      </section>

      {/* Step 2: brand + product */}
      <section className="mb-6 grid grid-cols-1 gap-4 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 md:grid-cols-2">
        <h2 className="font-semibold md:col-span-2">Бренд и продукт</h2>
        {target === "new_brand" && (
          <>
            <Field label="Название бренда">
              {({ inputProps }) => (
                <input
                  {...inputProps}
                  value={brandName}
                  onChange={(e) => {
                    setBrandName(e.target.value);
                  }}
                  className="h-9 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm"
                />
              )}
            </Field>
            <Field label="Slug бренда">
              {({ inputProps }) => (
                <input
                  {...inputProps}
                  value={brandSlug}
                  onChange={(e) => {
                    setBrandSlug(e.target.value);
                  }}
                  className="h-9 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 font-mono text-sm"
                />
              )}
            </Field>
            <Field label="Категория">
              {({ inputProps }) => (
                <select
                  {...inputProps}
                  value={categoryId}
                  onChange={(e) => {
                    setCategoryId(e.target.value);
                  }}
                  className="h-9 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm"
                >
                  <option value="">— выбери —</option>
                  {(categories.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.translations.find((t) => t.locale === "ru")?.name ?? c.slug}
                    </option>
                  ))}
                </select>
              )}
            </Field>
          </>
        )}
        <Field label="Название продукта">
          {({ inputProps }) => (
            <input
              {...inputProps}
              value={productName}
              onChange={(e) => {
                setProductName(e.target.value);
              }}
              className="h-9 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm"
            />
          )}
        </Field>
        <Field label="Slug продукта">
          {({ inputProps }) => (
            <input
              {...inputProps}
              value={productSlug}
              onChange={(e) => {
                setProductSlug(e.target.value);
              }}
              className="h-9 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 font-mono text-sm"
            />
          )}
        </Field>
        <Field label="Наценка, %">
          {({ inputProps }) => (
            <input
              {...inputProps}
              value={margin}
              onChange={(e) => {
                setMargin(e.target.value);
              }}
              inputMode="decimal"
              className="h-9 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm"
            />
          )}
        </Field>
        <div className="text-xs text-[var(--text-secondary)] md:col-span-2">
          Поля игрока (из G2B):{" "}
          {requiredFields.length ? requiredFields.map((f) => f.label.ru).join(", ") : "—"}
        </div>
      </section>

      {/* Step 3: denominations */}
      <section className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4">
        <h2 className="mb-3 font-semibold">Номиналы</h2>
        <DenominationTable
          rows={denoms.data?.items ?? []}
          loading={denoms.isLoading}
          margin={margin}
          rowState={rowState}
          setRow={setRow}
        />
      </section>
    </div>
  );
}
