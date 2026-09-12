import { Button, Input } from "@yupay/ui";
import { ChevronDown, ChevronUp, Plus, Trash2 } from "lucide-react";

import { T, type Locale } from "./types";

import type { FaqDraft } from "./form";

interface Props {
  locale: Locale;
  items: FaqDraft[];
  onChange: (items: FaqDraft[]) => void;
}

function visibleFor(items: FaqDraft[], locale: Locale): FaqDraft[] {
  return items
    .filter((row) => row.locale === locale)
    .sort((a, b) => a.sort_order - b.sort_order);
}

export function FaqEditor({ locale, items, onChange }: Props) {
  const visible = visibleFor(items, locale);

  function replace(next: FaqDraft[]): void {
    const others = items.filter((row) => row.locale !== locale);
    onChange([...others, ...next.map((row, i) => ({ ...row, sort_order: i }))]);
  }

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-medium">{T.form.faqs}</h2>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">{T.form.faqHint}</p>
      </div>
      {visible.length === 0 ? (
        <p className="text-sm text-[var(--text-secondary)]">{T.form.faqEmpty}</p>
      ) : null}
      {visible.map((row, index) => (
        <div
          key={`${row.locale}-${String(index)}`}
          className="space-y-2 rounded-md border border-[var(--border-default)] p-3"
        >
          <div className="flex justify-end gap-1">
            <Button
              type="button"
              variant="ghost"
              disabled={index === 0}
              onClick={() => {
                const next = [...visible];
                const swap = next[index - 1];
                const current = next[index];
                if (swap === undefined || current === undefined) return;
                next[index - 1] = current;
                next[index] = swap;
                replace(next);
              }}
              aria-label={T.form.faqUp}
            >
              <ChevronUp className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              disabled={index === visible.length - 1}
              onClick={() => {
                const next = [...visible];
                const swap = next[index + 1];
                const current = next[index];
                if (swap === undefined || current === undefined) return;
                next[index + 1] = current;
                next[index] = swap;
                replace(next);
              }}
              aria-label={T.form.faqDown}
            >
              <ChevronDown className="size-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                replace(visible.filter((_, i) => i !== index));
              }}
              aria-label={T.form.faqRemove}
            >
              <Trash2 className="size-4" />
            </Button>
          </div>
          <label className="block text-xs font-medium uppercase text-[var(--text-secondary)]">
            {T.form.faqQuestion}
            <Input
              className="mt-1"
              value={row.question}
              onChange={(e) => {
                replace(visible.map((item, i) => (i === index ? { ...item, question: e.target.value } : item)));
              }}
            />
          </label>
          <label className="block text-xs font-medium uppercase text-[var(--text-secondary)]">
            {T.form.faqAnswer}
            <textarea
              className="mt-1 min-h-16 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-sm"
              value={row.answer}
              onChange={(e) => {
                replace(visible.map((item, i) => (i === index ? { ...item, answer: e.target.value } : item)));
              }}
            />
          </label>
        </div>
      ))}
      <Button
        type="button"
        variant="ghost"
        onClick={() => {
          replace([
            ...visible,
            { locale, sort_order: visible.length, question: "", answer: "" },
          ]);
        }}
      >
        <Plus className="size-4" />
        {T.form.faqAdd}
      </Button>
    </section>
  );
}
