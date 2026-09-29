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
      <div className="border-border bg-card divide-border divide-y rounded-xl border">
        {entries.map((e) => (
          <details key={e.question} className="group px-4 py-3">
            <summary className="cursor-pointer list-none text-[14px] font-semibold">
              {e.question}
            </summary>
            <p className="text-tx-dim mt-2 text-[13px] leading-relaxed">{e.answer}</p>
          </details>
        ))}
      </div>
    </section>
  );
}
