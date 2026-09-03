"use client";

import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

/**
 * Collapsible "how do I find my Steam account's region" hint next to the
 * region selector's label. Mirrors `InviteGuide`'s box styling (border,
 * Info icon, muted text) but — unlike `InviteGuide`, which is always
 * rendered — stays collapsed until the buyer asks for it: the country
 * picker (flag + localized name) is already self-explanatory for most
 * buyers, so this hint only earns its screen space on demand.
 */
export function RegionHint() {
  const t = useTranslations("web.gifts.game");
  const [open, setOpen] = useState(false);

  return (
    <div>
      <button
        type="button"
        onClick={() => {
          setOpen((o) => !o);
        }}
        aria-expanded={open}
        className="text-primary shrink-0 text-[12px] font-semibold hover:underline"
      >
        {t("regionHintLink")}
      </button>
      {open && (
        <div className="border-border bg-muted/40 mt-2 rounded-lg border p-3 text-[13px]">
          <p className="text-foreground flex items-start gap-1.5">
            <Info size={14} className="text-tx-dim mt-0.5 shrink-0" aria-hidden="true" />
            <span className="text-tx-mute leading-snug">{t("regionHintText")}</span>
          </p>
        </div>
      )}
    </div>
  );
}
