import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { Plus, Trash2, Wand2 } from "lucide-react";
import { useEffect, useMemo } from "react";
import { Controller, useForm, useFieldArray } from "react-hook-form";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { z } from "zod";

import type { Brand, Product, Sku } from "../types";

import { ImageUploader } from "@/components/ImageUploader";
import { PageHeader } from "@/components/PageHeader";
import { ApiError, apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

const CURRENCIES = ["USD", "USDT", "RUB", "UZS", "KZT", "EUR"] as const;
const REGION_PRESETS = [
  { value: "GLOBAL", label: "GLOBAL" },
  { value: "TR", label: "TR · Турция" },
  { value: "US", label: "US · США" },
  { value: "RU", label: "RU · Россия" },
  { value: "UZ", label: "UZ · Узбекистан" },
  { value: "KZ", label: "KZ · Казахстан" },
  { value: "BR", label: "BR · Бразилия" },
  { value: "ID", label: "ID · Индонезия" },
  { value: "PH", label: "PH · Филиппины" },
  { value: "IN", label: "IN · Индия" },
] as const;

const priceOverrideSchema = z.object({
  currency: z.string().min(3).max(8),
  price: z.string().regex(/^\d+(\.\d{1,6})?$/, "число > 0"),
});

const skuSchema = z.object({
  product_id: z.string().min(1, "Выбери продукт"),
  sku_code: z
    .string()
    .min(1, "Обязательно")
    .max(64)
    .regex(/^[A-Za-z0-9._-]+$/, "только латиница, цифры, . _ -"),
  denomination: z.string().max(64).optional().nullable(),
  region: z.string().max(8).optional().nullable(),
  price_usd: z.string().regex(/^\d+(\.\d{1,6})?$/, "число > 0"),
  // Empty string is "no value" — we strip it before sending so the
  // backend keeps cost_usdt as NULL for SKUs whose wholesale cost
  // isn't known yet.
  cost_usdt: z
    .string()
    .regex(/^(\d+(\.\d{1,6})?)?$/, "число > 0 либо пусто")
    .optional()
    .nullable(),
  image_url: z.string().url().or(z.literal("")).optional().nullable(),
  sort_order: z.coerce.number().int().default(0),
  active: z.boolean().default(true),
  price_overrides: z.array(priceOverrideSchema).default([]),
});

type FormValues = z.infer<typeof skuSchema>;

const EMPTY: FormValues = {
  product_id: "",
  sku_code: "",
  denomination: "",
  region: "GLOBAL",
  price_usd: "1.00",
  cost_usdt: "",
  image_url: "",
  sort_order: 0,
  active: true,
  price_overrides: [],
};

interface SkuCreateBody {
  product_id: string;
  sku_code: string;
  denomination: string | null;
  region: string | null;
  price_usd: string;
  cost_usdt: string | null;
  image_url: string | null;
  sort_order: number;
  active: boolean;
  price_overrides: { currency: string; price: string }[];
}

interface SkuPatchBody {
  sku_code: string;
  denomination: string | null;
  region: string | null;
  price_usd: string;
  cost_usdt: string | null;
  image_url: string | null;
  sort_order: number;
  active: boolean;
  price_overrides: { currency: string; price: string }[];
}

export function SkuEditPage() {
  const params = useParams<{ id?: string }>();
  const [search] = useSearchParams();
  const isNew = !params.id;
  const navigate = useNavigate();
  const qc = useQueryClient();

  const productsQuery = useQuery<Product[]>({
    queryKey: qk.products(),
    queryFn: () => apiGet<Product[]>("/api/v1/admin/catalog/products"),
  });
  const brandsQuery = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });

  // Walk the list to find the existing SKU — same pattern as ProductEditPage.
  const skusQuery = useQuery<Sku[]>({
    queryKey: qk.skus(),
    queryFn: () => apiGet<Sku[]>("/api/v1/admin/catalog/skus"),
  });
  const existing = isNew ? null : skusQuery.data?.find((s) => s.id === params.id);

  const form = useForm<FormValues>({
    resolver: zodResolver(skuSchema),
    defaultValues: EMPTY,
  });
  const overrides = useFieldArray({
    control: form.control,
    name: "price_overrides",
  });

  // Initial preselect of product_id from ?product_id= when creating from a product card.
  useEffect(() => {
    if (isNew) {
      const preset = search.get("product_id");
      if (preset && !form.getValues("product_id")) {
        form.setValue("product_id", preset, { shouldValidate: false });
      }
    }
  }, [isNew, search, form]);

  // Wait for products to land before resetting — otherwise the
  // ``<select name="product_id">`` has no matching ``<option>`` and snaps
  // back to "— Выбери —". Same pattern as BrandEditPage / ProductEditPage.
  const productsReady = (productsQuery.data?.length ?? 0) > 0;
  useEffect(() => {
    if (!existing || !productsReady) return;
    form.reset({
      product_id: existing.product_id,
      sku_code: existing.sku_code,
      denomination: existing.denomination ?? "",
      region: existing.region ?? "GLOBAL",
      price_usd: existing.price_usd,
      cost_usdt: existing.cost_usdt ?? "",
      image_url: existing.image_url ?? "",
      sort_order: existing.sort_order,
      active: existing.active,
      price_overrides: existing.price_overrides.map((o) => ({
        currency: o.currency,
        price: o.price,
      })),
    });
  }, [existing, productsReady, form]);

  const productById = useMemo(() => {
    const map = new Map<string, Product>();
    for (const p of productsQuery.data ?? []) map.set(p.id, p);
    return map;
  }, [productsQuery.data]);
  const brandById = useMemo(() => {
    const map = new Map<string, Brand>();
    for (const b of brandsQuery.data ?? []) map.set(b.id, b);
    return map;
  }, [brandsQuery.data]);

  const watchedProductId = form.watch("product_id");
  const watchedDenom = form.watch("denomination");
  const watchedRegion = form.watch("region");
  const watchedPriceUsd = form.watch("price_usd");
  const watchedSkuCode = form.watch("sku_code");

  const selectedProduct = watchedProductId ? productById.get(watchedProductId) : undefined;
  const selectedBrand = selectedProduct ? brandById.get(selectedProduct.brand_id) : undefined;
  const productName =
    selectedProduct?.translations.find((t) => t.locale === "ru")?.name ??
    selectedProduct?.slug ??
    "";
  const brandName =
    selectedBrand?.translations.find((t) => t.locale === "ru")?.name ?? selectedBrand?.slug ?? "";

  const suggestSkuCode = () => {
    if (!selectedProduct) return;
    const base = selectedProduct.slug;
    const denom = (watchedDenom ?? "")
      .toString()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
    const region = (watchedRegion ?? "").toLowerCase();
    const parts = [base, denom, region].filter(Boolean);
    form.setValue("sku_code", parts.join("-"), {
      shouldValidate: true,
      shouldDirty: true,
    });
  };

  const save = useMutation<Sku, ApiError, FormValues>({
    mutationFn: async (values) => {
      const costNorm = values.cost_usdt?.trim() || null;
      if (isNew) {
        const body: SkuCreateBody = {
          product_id: values.product_id,
          sku_code: values.sku_code,
          denomination: values.denomination?.trim() || null,
          region: values.region?.trim() || null,
          price_usd: values.price_usd,
          cost_usdt: costNorm,
          image_url: values.image_url?.trim() || null,
          sort_order: values.sort_order,
          active: values.active,
          price_overrides: values.price_overrides.map((o) => ({
            currency: o.currency.toUpperCase(),
            price: o.price,
          })),
        };
        return apiPost<Sku>("/api/v1/admin/catalog/skus", body);
      }
      const body: SkuPatchBody = {
        sku_code: values.sku_code,
        denomination: values.denomination?.trim() || null,
        region: values.region?.trim() || null,
        price_usd: values.price_usd,
        cost_usdt: costNorm,
        image_url: values.image_url?.trim() || null,
        sort_order: values.sort_order,
        active: values.active,
        price_overrides: values.price_overrides.map((o) => ({
          currency: o.currency.toUpperCase(),
          price: o.price,
        })),
      };
      return apiPatch<Sku>(`/api/v1/admin/catalog/skus/${params.id ?? ""}`, body);
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.skus() });
      navigate("/skus");
    },
  });

  const remove = useMutation<void, ApiError>({
    mutationFn: () => apiDelete(`/api/v1/admin/catalog/skus/${params.id ?? ""}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.skus() });
      navigate("/skus");
    },
  });

  const denominationHint =
    selectedProduct?.kind === "voucher"
      ? "Например: «10 USD», «1 месяц», «Premium 3 мес»"
      : "Например: «60 UC», «120 UC», «660 UC», «Royale Pass»";

  return (
    <form
      onSubmit={form.handleSubmit((v) => {
        save.mutate(v);
      })}
    >
      <PageHeader
        title={isNew ? "Новый SKU" : `SKU · ${existing?.sku_code ?? params.id?.slice(0, 8) ?? ""}`}
        description={
          selectedProduct
            ? `${brandName} → ${productName} → конкретная позиция к продаже.`
            : "Конкретная продаваемая позиция: номинал + регион + цена."
        }
        actions={
          <>
            <Button type="button" variant="ghost" onClick={() => navigate("/skus")}>
              Отмена
            </Button>
            {!isNew && (
              <Button
                type="button"
                variant="danger"
                onClick={() => {
                  if (confirm(`Удалить SKU «${existing?.sku_code ?? ""}»? Действие необратимо.`)) {
                    remove.mutate();
                  }
                }}
                disabled={remove.isPending}
              >
                <Trash2 className="size-4" />
                Удалить
              </Button>
            )}
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? "Сохранение…" : "Сохранить"}
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* ----- left: identity + pricing ----- */}
        <section className="space-y-4 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)] lg:col-span-2">
          <Field
            label="Продукт"
            error={form.formState.errors.product_id?.message}
            help="К какому бренд-продукту относится этот SKU."
          >
            <select
              {...form.register("product_id")}
              disabled={!isNew}
              className="flex h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm disabled:opacity-60"
            >
              <option value="">— Выбери продукт —</option>
              {productsQuery.data?.map((p) => {
                const brand = brandById.get(p.brand_id);
                const brandLabel =
                  brand?.translations.find((t) => t.locale === "ru")?.name ?? brand?.slug ?? "?";
                const pName = p.translations.find((t) => t.locale === "ru")?.name ?? p.slug;
                return (
                  <option key={p.id} value={p.id}>
                    {brandLabel} — {pName}
                  </option>
                );
              })}
            </select>
            {!isNew && (
              <p className="mt-1 text-xs text-[var(--text-secondary)]">
                Продукт у существующего SKU поменять нельзя — удали и создай заново.
              </p>
            )}
          </Field>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Номинал" help={denominationHint}>
              <Input {...form.register("denomination")} placeholder="60 UC" />
            </Field>
            <Field label="Регион" help="GLOBAL — продаётся везде.">
              <select
                {...form.register("region")}
                className="flex h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm"
              >
                {REGION_PRESETS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field
            label="SKU code"
            error={form.formState.errors.sku_code?.message}
            help="Уникальный идентификатор. Можно сгенерировать из продукта + номинала + региона."
          >
            <div className="flex gap-2">
              <Input
                {...form.register("sku_code")}
                placeholder="pubg-uc-60-tr"
                className="font-mono"
              />
              <Button
                type="button"
                variant="secondary"
                size="md"
                onClick={suggestSkuCode}
                disabled={!selectedProduct}
                title="Сгенерировать из продукта + номинала + региона"
              >
                <Wand2 className="size-4" />
                Сгенерировать
              </Button>
            </div>
          </Field>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field
              label="Цена USD (retail)"
              error={form.formState.errors.price_usd?.message}
              help="Каноническая цена для юзера. Конвертируется по FX, если нет override."
            >
              <div className="flex items-center gap-2">
                <span className="text-sm text-[var(--text-secondary)]">$</span>
                <Input
                  {...form.register("price_usd")}
                  inputMode="decimal"
                  placeholder="0.85"
                  className="font-mono"
                />
              </div>
            </Field>
            <Field
              label="Cost USDT (поставщику)"
              error={form.formState.errors.cost_usdt?.message}
              help="Сколько мы платим поставщику. Из этого считается UZS-цена при bulk-recompute и margin = price − cost."
            >
              <div className="flex items-center gap-2">
                <span className="text-sm text-[var(--text-secondary)]">₮</span>
                <Input
                  {...form.register("cost_usdt")}
                  inputMode="decimal"
                  placeholder="0.60"
                  className="font-mono"
                />
              </div>
            </Field>
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <Field label="Сортировка">
              <Input type="number" {...form.register("sort_order")} />
            </Field>
            <Field label="Статус">
              <label className="mt-1 flex h-10 items-center gap-2 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm">
                <input type="checkbox" {...form.register("active")} className="size-4" />
                Активен
              </label>
            </Field>
          </div>

          <Field
            label="Изображение"
            error={form.formState.errors.image_url?.message}
            help="Опционально. Переопределяет картинку продукта."
          >
            <Controller
              control={form.control}
              name="image_url"
              render={({ field }) => (
                <ImageUploader value={field.value} onChange={field.onChange} kind="sku_image" />
              )}
            />
          </Field>
        </section>

        {/* ----- right: preview + overrides ----- */}
        <aside className="space-y-4">
          <PricePreview
            productName={productName}
            denom={watchedDenom ?? ""}
            region={watchedRegion ?? ""}
            priceUsd={watchedPriceUsd}
            overrides={form.watch("price_overrides")}
            skuCode={watchedSkuCode}
          />

          <section className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
            <div className="mb-3 flex items-baseline justify-between">
              <div>
                <h3 className="text-sm font-semibold">Цены в других валютах</h3>
                <p className="text-xs text-[var(--text-secondary)]">
                  Перебивают FX-конвертацию. Оставь пустым — посчитается из USD.
                </p>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => {
                  overrides.append({ currency: "UZS", price: "" });
                }}
              >
                <Plus className="size-4" />
                Добавить
              </Button>
            </div>

            {overrides.fields.length === 0 ? (
              <p className="rounded-md border border-dashed border-[var(--border-default)] p-4 text-center text-xs text-[var(--text-secondary)]">
                Пусто. Все валюты берутся через FX из USD.
              </p>
            ) : (
              <ul className="space-y-2">
                {overrides.fields.map((field, idx) => (
                  <li key={field.id} className="flex items-center gap-2">
                    <select
                      {...form.register(`price_overrides.${idx}.currency`)}
                      className="h-9 w-24 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm font-medium"
                    >
                      {CURRENCIES.map((c) => (
                        <option key={c} value={c}>
                          {c}
                        </option>
                      ))}
                    </select>
                    <Input
                      {...form.register(`price_overrides.${idx}.price`)}
                      inputMode="decimal"
                      placeholder="0.00"
                      className="font-mono"
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        overrides.remove(idx);
                      }}
                      aria-label="Убрать"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </aside>
      </div>

      {save.isError && (
        <p className="mt-4 text-sm text-[var(--danger)]">
          {extractApiMessage(save.error) ?? "Не удалось сохранить SKU."}
        </p>
      )}
      {remove.isError && (
        <p className="mt-4 text-sm text-[var(--danger)]">
          {extractApiMessage(remove.error) ?? "Не удалось удалить."}
        </p>
      )}
    </form>
  );
}

function PricePreview({
  productName,
  denom,
  region,
  priceUsd,
  overrides,
  skuCode,
}: {
  productName: string;
  denom: string;
  region: string;
  priceUsd: string;
  overrides: { currency: string; price: string }[];
  skuCode: string;
}) {
  const usdNum = Number.parseFloat(priceUsd);
  const hasUsd = !Number.isNaN(usdNum) && usdNum > 0;
  const validOverrides = overrides.filter((o) => {
    const n = Number.parseFloat(o.price);
    return !Number.isNaN(n) && n > 0 && o.currency.length >= 3;
  });
  const showLine = denom || region || hasUsd;
  return (
    <section className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Превью
      </h3>
      {!showLine ? (
        <p className="text-sm text-[var(--text-secondary)]">
          Заполни номинал, регион и цену — здесь появится итог.
        </p>
      ) : (
        <div className="space-y-3">
          <div>
            <div className="text-base font-semibold">
              {productName || "Продукт"} ·{" "}
              <span className="text-[var(--accent)]">{denom || "—"}</span>
            </div>
            <div className="text-xs text-[var(--text-secondary)]">
              регион {region || "—"} · код{" "}
              <code className="text-[var(--text-primary)]">{skuCode || "—"}</code>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {hasUsd && <PriceChip currency="USD" value={usdNum.toFixed(2)} tone="primary" />}
            {validOverrides.map((o, i) => (
              <PriceChip
                key={`${o.currency}-${i}`}
                currency={o.currency.toUpperCase()}
                value={Number.parseFloat(o.price).toLocaleString("ru-RU", {
                  maximumFractionDigits: 2,
                })}
                tone="override"
              />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

function PriceChip({
  currency,
  value,
  tone,
}: {
  currency: string;
  value: string;
  tone: "primary" | "override";
}) {
  const cls =
    tone === "primary"
      ? "border-[var(--accent)]/30 bg-[var(--accent)]/10 text-[var(--accent)]"
      : "border-[var(--border-default)] bg-[var(--bg-muted)] text-[var(--text-primary)]";
  return (
    <span
      className={`inline-flex items-baseline gap-1 rounded-md border px-2 py-1 font-mono text-xs ${cls}`}
    >
      <span className="text-[10px] uppercase tracking-wide opacity-70">{currency}</span>
      <span className="text-sm font-semibold">{value}</span>
    </span>
  );
}

function Field({
  label,
  error,
  help,
  children,
}: {
  label: string;
  error?: string | undefined;
  help?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
        {label}
      </span>
      <div className="mt-1">{children}</div>
      {help && !error && (
        <span className="mt-1 block text-xs text-[var(--text-secondary)]">{help}</span>
      )}
      {error && <span className="mt-1 block text-xs text-[var(--danger)]">{error}</span>}
    </label>
  );
}

function extractApiMessage(err: unknown): string | undefined {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string; title?: string } | null;
    return body?.detail ?? body?.title ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return undefined;
}
