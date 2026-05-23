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
import type { Category } from "../types";

const LOCALES = ["ru", "en", "uz"] as const;

const translationSchema = z.object({
  locale: z.enum(LOCALES),
  name: z.string().min(1, "Обязательно"),
  description: z.string().optional().nullable(),
});

const categorySchema = z.object({
  slug: z.string().regex(/^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/, "латиница, цифры, дефис"),
  icon: z.string().optional().or(z.literal("")).nullable(),
  sort_order: z.coerce.number().int().default(0),
  active: z.boolean().default(true),
  translations: z.array(translationSchema).min(1),
});

type FormValues = z.infer<typeof categorySchema>;

const EMPTY: FormValues = {
  slug: "",
  icon: "",
  sort_order: 0,
  active: true,
  translations: LOCALES.map((l) => ({ locale: l, name: "", description: "" })),
};

function nullEmptyStrings<T extends Record<string, unknown>>(o: T): T {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(o)) {
    out[k] = v === "" ? null : v;
  }
  return out as T;
}

export function CategoryEditPage() {
  const params = useParams<{ id?: string }>();
  const isNew = !params.id;
  const navigate = useNavigate();
  const qc = useQueryClient();

  // No GET-by-id on the public surface; walk the list like the other edit pages do.
  const categoriesQuery = useQuery<Category[]>({
    queryKey: qk.categories(),
    queryFn: () => apiGet<Category[]>("/api/v1/admin/catalog/categories"),
  });
  const existing = isNew ? null : categoriesQuery.data?.find((c) => c.id === params.id);

  const form = useForm<FormValues>({
    resolver: zodResolver(categorySchema),
    defaultValues: EMPTY,
  });
  const { fields } = useFieldArray({ control: form.control, name: "translations" });

  useEffect(() => {
    if (existing) {
      form.reset({
        slug: existing.slug,
        icon: existing.icon ?? "",
        sort_order: existing.sort_order,
        active: existing.active,
        translations: LOCALES.map((locale) => {
          const t = existing.translations.find((x) => x.locale === locale);
          return {
            locale,
            name: t?.name ?? "",
            description: t?.description ?? "",
          };
        }),
      });
    }
  }, [existing, form]);

  const save = useMutation({
    mutationFn: async (values: FormValues) => {
      const payload = nullEmptyStrings(values);
      if (isNew) {
        return apiPost<Category>("/api/v1/admin/catalog/categories", payload);
      }
      return apiPatch<Category>(
        `/api/v1/admin/catalog/categories/${params.id ?? ""}`,
        payload,
      );
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.categories() });
      navigate("/categories");
    },
  });

  const remove = useMutation({
    mutationFn: () =>
      apiDelete(`/api/v1/admin/catalog/categories/${params.id ?? ""}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.categories() });
      navigate("/categories");
    },
  });

  return (
    <form onSubmit={form.handleSubmit((v) => save.mutate(v))}>
      <PageHeader
        title={isNew ? "Новая категория" : "Редактирование категории"}
        description="Верхний уровень навигации — «Игры», «Подписки», «Подарочные карты»."
        actions={
          <>
            <Button type="button" variant="ghost" onClick={() => navigate("/categories")}>
              Отмена
            </Button>
            {!isNew && (
              <Button
                type="button"
                variant="danger"
                onClick={() => {
                  if (
                    confirm(
                      "Удалить категорию? Бренды и продукты этой категории не удалятся, но останутся без родителя.",
                    )
                  ) {
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

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <section className="space-y-4 rounded-lg border bg-[var(--bg-surface)] p-4">
          <Field label="Slug" error={form.formState.errors.slug?.message}>
            <Input {...form.register("slug")} placeholder="games" className="font-mono" />
          </Field>
          <Field
            label="Иконка"
            help="Произвольная строка — обычно имя lucide-иконки (например, gamepad-2)."
          >
            <Input {...form.register("icon")} placeholder="gamepad-2" />
          </Field>
          <div className="flex gap-4">
            <Field label="Порядок">
              <Input
                type="number"
                {...form.register("sort_order")}
                className="w-24"
              />
            </Field>
            <Field label="Статус">
              <label className="mt-1 flex h-10 items-center gap-2 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm">
                <input type="checkbox" {...form.register("active")} className="size-4" />
                Активна
              </label>
            </Field>
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
      {remove.isError && (
        <p className="mt-4 text-sm text-[var(--danger)]">
          {remove.error instanceof Error ? remove.error.message : "Не удалось удалить"}
        </p>
      )}
    </form>
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
      {error && (
        <span className="mt-1 block text-xs text-[var(--danger)]">{error}</span>
      )}
    </label>
  );
}
