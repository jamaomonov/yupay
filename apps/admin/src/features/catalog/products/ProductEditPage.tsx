import { useEffect } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { z } from "zod";
import { Trash2 } from "lucide-react";

import { Button, Input } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { Brand, Product } from "../types";
import { RequiredFieldsEditor } from "../form-schema/RequiredFieldsEditor";

const LOCALES = ["ru", "en", "uz"] as const;

const localeMap = z.record(z.string(), z.string());
const formOption = z.object({ value: z.string().min(1), label: localeMap });
const formField = z.object({
  key: z.string().min(1),
  label: localeMap,
  type: z.enum(["text", "email", "number", "select"]),
  required: z.boolean().default(true),
  placeholder: localeMap.optional().nullable(),
  help_text: localeMap.optional().nullable(),
  pattern: z.string().optional().nullable(),
  options: z.array(formOption).optional().nullable(),
});

const translationSchema = z.object({
  locale: z.enum(LOCALES),
  name: z.string().min(1),
  short_description: z.string().optional().nullable(),
  description: z.string().optional().nullable(),
});

const productSchema = z.object({
  slug: z.string().regex(/^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/),
  brand_id: z.string().min(1),
  kind: z.enum(["top_up", "voucher"]),
  supplier_hint: z.string().optional().nullable(),
  image_url: z.string().optional().or(z.literal("")).nullable(),
  sort_order: z.coerce.number().int().default(0),
  active: z.boolean().default(true),
  required_fields: z.array(formField).default([]),
  translations: z.array(translationSchema).min(1),
});

type FormValues = z.infer<typeof productSchema>;

const EMPTY: FormValues = {
  slug: "",
  brand_id: "",
  kind: "top_up",
  supplier_hint: "",
  image_url: "",
  sort_order: 0,
  active: true,
  required_fields: [],
  translations: LOCALES.map((l) => ({ locale: l, name: "", short_description: "" })),
};

export function ProductEditPage() {
  const params = useParams<{ id?: string }>();
  const isNew = !params.id;
  const navigate = useNavigate();
  const qc = useQueryClient();

  const brandsQuery = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });

  const productsQuery = useQuery<Product[]>({
    queryKey: qk.products(),
    queryFn: () => apiGet<Product[]>("/api/v1/admin/catalog/products"),
  });
  const existing = isNew ? null : productsQuery.data?.find((p) => p.id === params.id);

  const form = useForm<FormValues>({
    resolver: zodResolver(productSchema),
    defaultValues: EMPTY,
  });
  const trans = useFieldArray({ control: form.control, name: "translations" });

  useEffect(() => {
    if (existing) {
      form.reset({
        slug: existing.slug,
        brand_id: existing.brand_id,
        kind: existing.kind,
        supplier_hint: existing.supplier_hint ?? "",
        image_url: existing.image_url ?? "",
        sort_order: existing.sort_order,
        active: existing.active,
        required_fields: existing.required_fields,
        translations: LOCALES.map((locale) => {
          const t = existing.translations.find((x) => x.locale === locale);
          return {
            locale,
            name: t?.name ?? "",
            short_description: t?.short_description ?? "",
            description: t?.description ?? "",
          };
        }),
      });
    }
  }, [existing, form]);

  const save = useMutation({
    mutationFn: async (values: FormValues) => {
      const payload = { ...values, image_url: values.image_url || null };
      if (isNew) return apiPost<Product>("/api/v1/admin/catalog/products", payload);
      return apiPatch<Product>(
        `/api/v1/admin/catalog/products/${params.id ?? ""}`,
        payload,
      );
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.products() });
      navigate("/products");
    },
  });

  const remove = useMutation({
    mutationFn: () => apiDelete(`/api/v1/admin/catalog/products/${params.id ?? ""}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.products() });
      navigate("/products");
    },
  });

  return (
    <form onSubmit={form.handleSubmit((v) => save.mutate(v))}>
      <PageHeader
        title={isNew ? "Новый продукт" : "Редактирование продукта"}
        description="UC, Royal Pass, Wallet, Premium — что-то одно конкретное у бренда."
        actions={
          <>
            {!isNew && (
              <Button
                type="button"
                variant="danger"
                onClick={() => {
                  if (confirm("Удалить продукт?")) remove.mutate();
                }}
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

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="space-y-4 rounded-lg border bg-[--color-bg] p-4">
          <Field label="Slug" error={form.formState.errors.slug?.message}>
            <Input {...form.register("slug")} placeholder="pubg-uc" />
          </Field>
          <Field label="Brand" error={form.formState.errors.brand_id?.message}>
            <select
              {...form.register("brand_id")}
              className="flex h-10 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 text-sm"
            >
              <option value="">— Выбери —</option>
              {brandsQuery.data?.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.translations.find((t) => t.locale === "ru")?.name ?? b.slug}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Тип">
            <select
              {...form.register("kind")}
              className="flex h-10 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 text-sm"
            >
              <option value="top_up">top_up (прямое пополнение)</option>
              <option value="voucher">voucher (код)</option>
            </select>
          </Field>
          <Field label="Supplier hint">
            <Input {...form.register("supplier_hint")} placeholder="codashop / kupikod" />
          </Field>
          <Field label="Image URL">
            <Input {...form.register("image_url")} />
          </Field>
          <div className="flex gap-4">
            <Field label="Порядок">
              <Input type="number" {...form.register("sort_order")} className="w-24" />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" {...form.register("active")} />
              Активен
            </label>
          </div>
        </section>

        <section className="space-y-4 rounded-lg border bg-[--color-bg] p-4">
          <h2 className="font-medium">Переводы</h2>
          {trans.fields.map((field, idx) => (
            <fieldset key={field.id} className="space-y-2 rounded-md border p-3">
              <legend className="px-1 text-xs uppercase text-[--color-muted]">
                {field.locale}
              </legend>
              <Input
                placeholder="Название"
                {...form.register(`translations.${idx}.name`)}
              />
              <Input
                placeholder="Короткое описание"
                {...form.register(`translations.${idx}.short_description`)}
              />
              <textarea
                placeholder="Описание"
                {...form.register(`translations.${idx}.description`)}
                className="min-h-20 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 py-2 text-sm"
              />
            </fieldset>
          ))}
        </section>
      </div>

      <section className="mt-6 rounded-lg border bg-[--color-bg] p-4">
        <h2 className="mb-3 font-medium">Поля формы (required_fields)</h2>
        <p className="mb-3 text-sm text-[--color-muted]">
          Эти поля фронт показывает покупателю перед оплатой (player_id, сервер и пр.).
        </p>
        <RequiredFieldsEditor
          /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
          control={form.control as any}
          /* eslint-disable-next-line @typescript-eslint/no-explicit-any */
          register={form.register as any}
          name="required_fields"
        />
      </section>

      {save.isError && (
        <p className="mt-4 text-sm text-[--color-danger]">
          {save.error instanceof Error ? save.error.message : "Не удалось сохранить"}
        </p>
      )}
    </form>
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
      <span className="text-xs font-medium uppercase text-[--color-muted]">{label}</span>
      <div className="mt-1">{children}</div>
      {error && <span className="mt-1 block text-xs text-[--color-danger]">{error}</span>}
    </label>
  );
}
