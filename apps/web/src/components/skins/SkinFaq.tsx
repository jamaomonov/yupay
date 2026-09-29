import { ChevronDown } from "lucide-react";

import type { FaqEntry } from "@/lib/skin-seo";

import { JsonLd } from "@/components/JsonLd";

/**
 * The item's questions and answers, open on the page and as FAQPage JSON-LD — the same
 * text in both, as search engines require. Built by `skinFaq` from the item's own numbers.
 *
 * No `"use client"`: `<details>` needs no script.
 */
export function SkinFaq({ title, entries }: { title: string; entries: FaqEntry[] }) {
  if (entries.length === 0) return null;
  const ld = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: entries.map((e) => ({
      "@type": "Question",
      name: e.question,
      acceptedAnswer: { "@type": "Answer", text: e.answer },
    })),
  };
  return (
    <section className="mt-8" aria-labelledby="skin-faq">
      <JsonLd data={ld} />
      <h2 id="skin-faq" className="mb-3 text-[17px] font-bold">
        {title}
      </h2>
      <div className="space-y-2">
        {entries.map((e) => (
          <details
            key={e.question}
            className="border-border bg-card hover:border-border-2 open:border-primary/40 group rounded-xl border transition-colors"
          >
            <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3.5 text-[14px] font-semibold [&::-webkit-details-marker]:hidden">
              <span className="flex-1">{e.question}</span>
              <span
                aria-hidden
                className="border-border-2 text-tx-dim group-open:border-primary group-open:bg-primary group-open:text-primary-foreground flex size-7 shrink-0 items-center justify-center rounded-full border transition"
              >
                <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
              </span>
            </summary>
            <p className="text-tx-mute -mt-1 px-4 pb-4 pr-14 text-[14px] leading-relaxed">
              {e.answer}
            </p>
          </details>
        ))}
      </div>
    </section>
  );
}
