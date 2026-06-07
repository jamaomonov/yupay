import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { Trash2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useParams } from "react-router-dom";
import { z } from "zod";

import type { Brand, BrandFaq } from "../types";

import { PageHeader } from "@/components/PageHeader";
import { apiDelete, apiGet, apiPatch, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

const LOCALES = ["ru", "en", "uz"] as const;

const faqSchema = z.object({
  sort_order: z.coerce.number().int().default(0),
  active: z.boolean().default(true),
  translations: z
    .array(
      z.object({
        locale: z.enum(LOCALES),
        question: z.string().min(1, "Обязательно"),
        answer: z.string().min(1, "Обязательно"),
      }),
    )
    .length(3),
});
type FaqForm = z.infer<typeof faqSchema>;

function emptyForm(sortOrder: number): FaqForm {
  return {
    sort_order: sortOrder,
    active: true,
    translations: LOCALES.map((locale) => ({ locale, question: "", answer: "" })),
  };
}

function fromFaq(faq: BrandFaq): FaqForm {
  return {
    sort_order: faq.sort_order,
    active: faq.active,
    translations: LOCALES.map((locale) => {
      const t = faq.translations.find((x) => x.locale === locale);
      return { locale, question: t?.question ?? "", answer: t?.answer ?? "" };
    }),
  };
}

function FaqCard({
  brandId,
  faq,
  defaultSort,
  onDone,
}: {
  brandId: string;
  /** null => a new (draft) FAQ that POSTs on save. */
  faq: BrandFaq | null;
  defaultSort: number;
  /** Called after a draft is saved/cancelled so the page can drop it. */
  onDone?: () => void;
}) {
  const qc = useQueryClient();
  const isNew = faq === null;
  const form = useForm<FaqForm>({
    resolver: zodResolver(faqSchema),
    defaultValues: faq ? fromFaq(faq) : emptyForm(defaultSort),
  });

  const save = useMutation({
    mutationFn: (v: FaqForm) =>
      isNew
        ? apiPost<BrandFaq>(`/api/v1/admin/catalog/brands/${brandId}/faqs`, v)
        : apiPatch<BrandFaq>(`/api/v1/admin/catalog/faqs/${faq.id}`, v),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.brandFaqs(brandId) });
      onDone?.();
    },
  });

  const remove = useMutation({
    mutationFn: () => apiDelete(`/api/v1/admin/catalog/faqs/${faq?.id ?? ""}`),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: qk.brandFaqs(brandId) });
      onDone?.();
    },
  });

  return (
    <form
      onSubmit={form.handleSubmit((v) => {
        save.mutate(v);
      })}
      className="space-y-3 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]"
    >
      <div className="flex flex-wrap items-center gap-4">
        <label className="text-xs font-medium uppercase text-[var(--text-secondary)]">
          Порядок
          <Input type="number" {...form.register("sort_order")} className="mt-1 w-20" />
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" {...form.register("active")} />
          Активен
        </label>
        <div className="ml-auto flex gap-2">
          {!isNew && (
            <Button
              type="button"
              variant="danger"
              onClick={() => {
                if (confirm("Удалить вопрос?")) remove.mutate();
              }}
            >
              <Trash2 className="size-4" />
              Удалить
            </Button>
          )}
          {isNew && (
            <Button type="button" variant="ghost" onClick={onDone}>
              Отмена
            </Button>
          )}
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Сохранение…" : "Сохранить"}
          </Button>
        </div>
      </div>

      {LOCALES.map((loc, idx) => (
        <fieldset key={loc} className="space-y-2 rounded-md border p-3">
          <legend className="px-1 text-xs uppercase text-[var(--text-secondary)]">{loc}</legend>
          <label className="block">
            <span className="text-xs font-medium uppercase text-[var(--text-secondary)]">
              Вопрос
            </span>
            <Input className="mt-1" {...form.register(`translations.${idx}.question`)} />
            {form.formState.errors.translations?.[idx]?.question && (
              <span className="mt-1 block text-xs text-[var(--danger)]">Обязательно</span>
            )}
          </label>
          <label className="block">
            <span className="text-xs font-medium uppercase text-[var(--text-secondary)]">Ответ</span>
            <textarea
              {...form.register(`translations.${idx}.answer`)}
              className="mt-1 min-h-16 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-sm"
            />
            {form.formState.errors.translations?.[idx]?.answer && (
              <span className="mt-1 block text-xs text-[var(--danger)]">Обязательно</span>
            )}
          </label>
        </fieldset>
      ))}

      {save.isError && (
        <p className="text-sm text-[var(--danger)]">
          {save.error instanceof Error ? save.error.message : "Не удалось сохранить"}
        </p>
      )}
    </form>
  );
}

export function BrandFaqsPage() {
  const params = useParams<{ id: string }>();
  const brandId = params.id ?? "";
  const [draftKeys, setDraftKeys] = useState<number[]>([]);

  const brandsQuery = useQuery<Brand[]>({
    queryKey: qk.brands(),
    queryFn: () => apiGet<Brand[]>("/api/v1/admin/catalog/brands"),
  });
  const brand = brandsQuery.data?.find((b) => b.id === brandId);
  const brandName = brand?.translations.find((t) => t.locale === "ru")?.name ?? brand?.slug ?? "";

  const faqsQuery = useQuery<BrandFaq[]>({
    queryKey: qk.brandFaqs(brandId),
    queryFn: () => apiGet<BrandFaq[]>(`/api/v1/admin/catalog/brands/${brandId}/faqs`),
    enabled: Boolean(brandId),
  });
  const faqs = faqsQuery.data ?? [];
  const nextSort = faqs.length ? Math.max(...faqs.map((f) => f.sort_order)) + 1 : 0;

  return (
    <div>
      <PageHeader
        title={`FAQ${brandName ? ` · ${brandName}` : ""}`}
        description="Вопросы показываются на странице бренда (аккордеон) и отдаются как FAQPage structured data для SEO."
        actions={
          <Link to={`/brands/${brandId}`}>
            <Button variant="ghost">← К бренду</Button>
          </Link>
        }
      />

      <div className="space-y-4">
        {faqs.map((faq) => (
          <FaqCard key={faq.id} brandId={brandId} faq={faq} defaultSort={faq.sort_order} />
        ))}

        {draftKeys.map((key) => (
          <FaqCard
            key={`draft-${String(key)}`}
            brandId={brandId}
            faq={null}
            defaultSort={nextSort}
            onDone={() => {
              setDraftKeys((ks) => ks.filter((k) => k !== key));
            }}
          />
        ))}

        {faqs.length === 0 && draftKeys.length === 0 && (
          <p className="text-sm text-[var(--text-secondary)]">Пока нет ни одного вопроса.</p>
        )}

        <Button
          type="button"
          onClick={() => {
            setDraftKeys((ks) => [...ks, (ks.at(-1) ?? 0) + 1]);
          }}
        >
          + Добавить вопрос
        </Button>
      </div>
    </div>
  );
}
