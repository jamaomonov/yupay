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
import type { Brand, Category } from "../types";

const LOCALES = ["ru", "en", "uz"] as const;

const translationSchema = z.object({
  locale: z.enum(LOCALES),
  name: z.string().min(1, "Обязательно"),
  short_description: z.string().optional().nullable(),
  description: z.string().optional().nullable(),
});

const brandSchema = z.object({
  slug: z.string().regex(/^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/, "латиница, цифры, дефис"),
  category_id: z.string().min(1, "Выбери категорию"),
  logo_url: z.string().url().optional().or(z.literal("")).nullable(),
  hero_image_url: z.string().url().optional().or(z.literal("")).nullable(),
  accent_color: z.string().optional().or(z.literal("")).nullable(),
  sort_order: z.coerce.number().int().default(0),
  active: z.boolean().default(true),
  translations: z.array(translationSchema).min(1),
});

type FormValues = z.infer<typeof brandSchema>;

const EMPTY: FormValues = {
  slug: "",
  category_id: "",
  logo_url: "",
  hero_image_url: "",
  accent_color: "",
  sort_order: 0,
  active: true,
  translations: [
    { locale: "ru", name: "", short_description: "", description: "" },
    { locale: "en", name: "", short_description: "", description: "" },
    { locale: "uz", name: "", short_description: "", description: "" },
  ],
};

function nullEmptyStrings<T extends Record<string, unknown>>(o: T): T {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) {
    out[k] = v === "" ? null : v;
  }
  return out as T;
}

export function BrandEditPage() {
  const params = useParams<{ id?: string }>();
  const isNew = !params.id;
  const navigate = useNavigate();
  const qc = useQueryClient();

  const categoriesQuery = useQuery<Category[]>({
    queryKey: qk.categories(),
    queryFn: () => apiGet<Category[]>("/api/v1/admin/catalog/categories"),
  });

  const brandQuery = useQuery<Brand>({
    queryKey: qk.brand(params.id ?? ""),
    queryFn: () => apiGet<Brand>(`/api/v1/admin/catalog/brands`),
    enabled: false,
  });

  // Load existing brand by walking the list (we don't have a /brands/{id} read endpoint
  // wired up to public yet — the admin list is fine for one item).
  const brandsQuery = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });
  const existing = isNew ? null : brandsQuery.data?.find((b) => b.id === params.id);

  const form = useForm<FormValues>({
    resolver: zodResolver(brandSchema),
    defaultValues: EMPTY,
  });
  const { fields } = useFieldArray({ control: form.control, name: "translations" });

  // Wait for *both* the brand row and the categories list. Resetting the form
  // before categories arrive means the ``<select>`` has no ``<option>`` whose
  // value matches ``existing.category_id``, so the browser snaps back to the
  // empty "— Выбери —" placeholder and react-hook-form's uncontrolled select
  // never re-applies the right value once the options finally render.
  const categoriesReady = (categoriesQuery.data?.length ?? 0) > 0;
  useEffect(() => {
    if (!existing || !categoriesReady) return;
    form.reset({
      slug: existing.slug,
      category_id: existing.category_id,
      logo_url: existing.logo_url ?? "",
      hero_image_url: existing.hero_image_url ?? "",
      accent_color: existing.accent_color ?? "",
      sort_order: existing.sort_order,
      active: existing.active,
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
  }, [existing, categoriesReady, form]);

  const save = useMutation({
    mutationFn: async (values: FormValues) => {
      const payload = nullEmptyStrings(values);
      if (isNew) return apiPost<Brand>("/api/v1/admin/catalog/brands", payload);
      return apiPatch<Brand>(
        `/api/v1/admin/catalog/brands/${params.id ?? ""}`,
        payload,
      );
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.brands() });
      navigate("/brands");
    },
  });

  const remove = useMutation({
    mutationFn: () => apiDelete(`/api/v1/admin/catalog/brands/${params.id ?? ""}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.brands() });
      navigate("/brands");
    },
  });

  return (
    <form onSubmit={form.handleSubmit((v) => save.mutate(v))}>
      <PageHeader
        title={isNew ? "Новый бренд" : `Редактирование бренда`}
        description="Бренд = игра/сервис/вендор, который видит покупатель."
        actions={
          <>
            {!isNew && (
              <Button
                type="button"
                variant="danger"
                onClick={() => {
                  if (confirm("Удалить бренд?")) remove.mutate();
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
        <section className="space-y-4 rounded-lg border bg-[var(--bg-surface)] p-4">
          <Field label="Slug" error={form.formState.errors.slug?.message}>
            <Input {...form.register("slug")} placeholder="pubg-mobile" />
          </Field>
          <Field label="Категория" error={form.formState.errors.category_id?.message}>
            <select
              {...form.register("category_id")}
              className="flex h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm"
            >
              <option value="">— Выбери —</option>
              {categoriesQuery.data?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.translations.find((t) => t.locale === "ru")?.name ?? c.slug}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Logo URL"><Input {...form.register("logo_url")} /></Field>
          <Field label="Hero image URL"><Input {...form.register("hero_image_url")} /></Field>
          <Field label="Accent color (#hex)">
            <Input {...form.register("accent_color")} placeholder="#F2A900" />
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

        <section className="space-y-4 rounded-lg border bg-[var(--bg-surface)] p-4">
          <h2 className="font-medium">Переводы</h2>
          {fields.map((field, idx) => (
            <fieldset key={field.id} className="space-y-2 rounded-md border p-3">
              <legend className="px-1 text-xs uppercase text-[var(--text-secondary)]">
                {field.locale}
              </legend>
              <Field
                label="Название"
                error={form.formState.errors.translations?.[idx]?.name?.message}
              >
                <Input {...form.register(`translations.${idx}.name`)} />
              </Field>
              <Field label="Короткое описание">
                <Input {...form.register(`translations.${idx}.short_description`)} />
              </Field>
              <Field label="Описание">
                <textarea
                  {...form.register(`translations.${idx}.description`)}
                  className="min-h-20 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-sm"
                />
              </Field>
            </fieldset>
          ))}
        </section>
      </div>

      {save.isError && (
        <p className="mt-4 text-sm text-[var(--danger)]">
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
      <span className="text-xs font-medium uppercase text-[var(--text-secondary)]">{label}</span>
      <div className="mt-1">{children}</div>
      {error && <span className="mt-1 block text-xs text-[var(--danger)]">{error}</span>}
    </label>
  );
}
