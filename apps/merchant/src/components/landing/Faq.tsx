import { ChevronDown } from "lucide-react";

import type { FaqEntry } from "@/lib/jsonld";

/**
 * A page's visible questions, as native `<details>` disclosures.
 *
 * Shared by the landing (its five) and by `/telegram`, `/api` and `/faq`
 * (their own selections), because the same list has to be handed to
 * `faqPage()` for the `FAQPage` markup: structured data that does not match
 * what a visitor sees is against Google's guidelines, and the cheapest way to
 * guarantee the match is to render and to mark up the *same array*.
 *
 * `<details>` rather than a disclosure widget: it opens without JavaScript,
 * it is in the accessibility tree already, and crawlers read closed content.
 * No state, so nothing here hydrates — the chevron turns on `group-open:`.
 *
 * `questionTag` is off by default. On `/`, `/telegram` and `/api` the block
 * already sits under its own `<h2>`, and a second level of headings there
 * would say nothing the section heading has not. `/faq` is the page whose
 * entire body *is* the questions, so there it passes `"h2"` and each question
 * becomes a real heading — a `<summary>` may legally contain heading content.
 * Tailwind's preflight already strips a heading's size, weight and margin, so
 * `inline` is the whole adjustment.
 */
export function Faq({
  items,
  className = "",
  questionTag: Question,
}: {
  items: FaqEntry[];
  className?: string;
  questionTag?: "h2" | "h3";
}) {
  return (
    <div className={`space-y-2 ${className}`}>
      {items.map(({ q, a }) => (
        <details key={q} className="border-border bg-card group rounded-xl border p-5">
          <summary className="flex cursor-pointer list-none items-start justify-between gap-4 font-semibold">
            {Question ? <Question className="inline">{q}</Question> : q}
            <ChevronDown
              size={18}
              aria-hidden="true"
              className="text-tx-dim mt-0.5 shrink-0 transition-transform group-open:rotate-180"
            />
          </summary>
          <p className="text-tx-mute mt-3 text-sm leading-relaxed">{a}</p>
        </details>
      ))}
    </div>
  );
}
