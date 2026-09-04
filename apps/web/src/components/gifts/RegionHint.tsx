"use client";

import { Info } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * Collapsible "how do I find my Steam account's region" hint next to the
 * region selector's label. Mirrors `InviteGuide`'s box styling (border,
 * Info icon, muted text) but — unlike `InviteGuide`, which is always
 * rendered — stays collapsed until the buyer asks for it: the country
 * picker (flag + localized name) is already self-explanatory for most
 * buyers, so this hint only earns its screen space on demand.
 *
 * Split into a toggle and a panel (state lifted to the caller,
 * `GiftPurchasePanel`) rather than one component owning both: the label row
 * that holds the toggle is a `flex items-center` row shared with the
 * "Регион"/"Страна…" heading, and rendering the expanded panel as a child of
 * that row let the row's flex layout squeeze it down to ~285px of the
 * available 360px (2026-09-04 review). Rendering the panel as the row's
 * *sibling* instead gives it the full width.
 */
export function RegionHintToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  const t = useTranslations("web.gifts.game");
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-expanded={open}
      // `min-h-[44px]` mirrors `AboutText`'s "читать полностью" toggle — a
      // plain text link with no button chrome is otherwise a tap target a
      // few pixels tall (2026-09-04 a11y review).
      className="text-primary inline-flex min-h-[44px] shrink-0 items-center text-[12px] font-semibold hover:underline"
    >
      {t("regionHintLink")}
    </button>
  );
}

export function RegionHintPanel({ open }: { open: boolean }) {
  const t = useTranslations("web.gifts.game");
  if (!open) return null;
  return (
    <div className="border-border bg-muted/40 mt-2 rounded-lg border p-3 text-[13px]">
      <p className="text-foreground flex items-start gap-1.5">
        <Info size={14} className="text-tx-dim mt-0.5 shrink-0" aria-hidden="true" />
        <span className="text-tx-mute leading-snug">{t("regionHintText")}</span>
      </p>
    </div>
  );
}
