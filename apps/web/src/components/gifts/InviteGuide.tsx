import { useTranslations } from "next-intl";

/**
 * Static "where do I get this link" hint under the invite field — a plain
 * numbered checklist, no dialog. `WhereToFindModal` (the equivalent helper
 * on `PurchasePanel`) opens as a dialog specifically to leave room for
 * richer help later (screenshots, step images); this one has nothing to
 * grow into yet, so it renders inline instead.
 *
 * No heading: the old "Где взять ссылку на профиль" title just restated
 * `inviteLabel` ("Ссылка на профиль Steam получателя"), which sits directly
 * above this box — two sentences saying the same thing back to back
 * (2026-09-04 review). The numbered steps carry the box on their own.
 *
 * No `"use client"`: purely static markup, safe to import from either a
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
    <div className="border-border bg-muted/40 rounded-lg border p-3 text-[13px]">
      <ol className="text-tx-mute list-decimal space-y-1 pl-5 leading-snug">
        {steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </div>
  );
}
