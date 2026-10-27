import { IdCard, type LucideIcon, Ticket } from "lucide-react";

import type { BrandVariant } from "@/lib/catalog";
import type { MessageKey } from "@/lib/i18n";

import { useT } from "@/lib/i18n";

/** Label and picture per way of buying (migration 0108). */
const VARIANTS: Record<string, { label: MessageKey; icon: LucideIcon }> = {
  id: { label: "topup.variant.id", icon: IdCard },
  promo: { label: "topup.variant.promo", icon: Ticket },
};

interface VariantChipsProps {
  variants: BrandVariant[];
  /** The brand on screen — its chip is the pressed one. */
  current: string;
  /** Opens another variant's own screen (`/topup/<slug>`). */
  onPick: (slug: string) => void;
}

/**
 * «По ID / Промокод»: the ways to buy one game, each its own brand and screen —
 * Standoff 2 by player id and as promo codes. Styled like the region chips
 * below it, but a pick navigates: a variant is not a region of one brand.
 */
export function VariantChips({ variants, current, onPick }: VariantChipsProps) {
  const { t } = useT();
  return (
    <div>
      <div className="mb-2.5 text-xs font-semibold uppercase tracking-wide text-white/50">
        {t("topup.variantTitle")}
      </div>
      <div className="flex gap-2">
        {variants.map((v) => {
          const active = v.slug === current;
          const known = VARIANTS[v.code];
          const Icon = known?.icon;
          return (
            <button
              key={v.slug}
              type="button"
              aria-pressed={active}
              onClick={() => {
                if (!active) onPick(v.slug);
              }}
              className="flex items-center gap-1.5 rounded-2xl px-3.5 py-2 text-xs font-semibold transition-all duration-150"
              style={{
                background: active ? "hsl(var(--surface-3))" : "hsl(var(--surface-2))",
                color: active ? "#fff" : "rgba(255,255,255,0.6)",
                border: active
                  ? "1.5px solid hsl(var(--primary) / 0.7)"
                  : "1px solid hsl(var(--border))",
              }}
            >
              {Icon && (
                <Icon size={15} aria-hidden className={active ? "text-primary" : undefined} />
              )}
              {known ? t(known.label) : v.code}
            </button>
          );
        })}
      </div>
    </div>
  );
}
