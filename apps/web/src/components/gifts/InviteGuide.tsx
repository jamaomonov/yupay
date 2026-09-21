import { ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * "Where do I get this link" — the three steps that produce a Steam profile
 * URL, behind a disclosure.
 *
 * **Collapsed by default** (owner direction, 2026-09-21: «инструкцию надо
 * сделать раскрывающимся либо в окне при нажатии как у других брендов»).
 * Open, it was a bordered five-line box wedged between the recipient field
 * and the Buy button, and every buyer who already knew how to copy a profile
 * link — which is most of the second order onward — had to read past it. The
 * rest of the store puts this kind of help behind a tap: `WhereToFindModal`
 * on `PurchasePanel`, `<details>` on the FAQ blocks.
 *
 * A `<details>` rather than that modal, of the two shapes the direction
 * allowed: the modal's body is plain text and these steps are an ordered
 * list, the disclosure needs no client JS in a tree that is already heavy,
 * and it keeps the steps in the document for a reader who prints or
 * translates the page.
 *
 * **The heading is back, and it is not the redundancy it was.** It was
 * removed on 2026-09-04 for restating `inviteLabel` directly above it — true
 * of a box that is always open, where the title is the second sentence
 * saying the same thing. Collapsed, the title is the only affordance: with
 * no label there is nothing to tell a reader the steps exist.
 *
 * No `"use client"`: `<details>` is markup, safe to import from either a
 * Server or Client tree (see `GiftCard`'s note on the same `useTranslations`
 * dual-runtime trick) — but it only ever renders inside `GiftPurchasePanel`
 * ("use client"), so it ships in the client bundle either way.
 */
export function InviteGuide() {
  const t = useTranslations("web.gifts.game");
  // Known-shape JSON array of localized guide steps — same `t.raw()`
  // pattern the legal pages use for their `sections` arrays.
  const steps = t.raw("inviteGuideSteps") as string[];

  return (
    <details className="border-border bg-muted/40 group rounded-lg border">
      <summary className="text-tx-mute flex cursor-pointer list-none items-center justify-between gap-3 p-3 text-[13px] font-medium [&::-webkit-details-marker]:hidden">
        {t("inviteGuideTitle")}
        <ChevronRight
          size={15}
          aria-hidden="true"
          className="text-tx-dim shrink-0 transition group-open:rotate-90"
        />
      </summary>
      <ol className="text-tx-mute list-decimal space-y-1 pb-3 pl-8 pr-3 text-[13px] leading-snug">
        {steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </details>
  );
}
