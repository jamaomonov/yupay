import { Info } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * Static "where do I get this link" hint under the invite field — a plain
 * numbered checklist, no dialog. `WhereToFindModal` (the equivalent helper
 * on `PurchasePanel`) opens as a dialog specifically to leave room for
 * richer help later (screenshots, step images); this one has nothing to
 * grow into yet, so it renders inline instead.
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
      <p className="text-foreground flex items-center gap-1.5 font-semibold">
        <Info size={14} className="text-tx-dim shrink-0" aria-hidden="true" />
        {t("inviteGuideTitle")}
      </p>
      <ol className="text-tx-mute mt-2 list-decimal space-y-1 pl-5 leading-snug">
        {steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </div>
  );
}
