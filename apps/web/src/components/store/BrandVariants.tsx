import { IdCard, type LucideIcon, Ticket } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { BrandVariant } from "@/lib/catalog";

import { brandPath } from "@/lib/brand-href";
import { pathFor } from "@/lib/seo";

/** A picture per way of buying, so the two chips read at a glance. */
const ICONS: Record<string, LucideIcon> = { id: IdCard, promo: Ticket };

interface BrandVariantsProps {
  variants: BrandVariant[];
  /** The page being shown — its chip is the pressed one. */
  current: string;
  locale: string;
}

/**
 * «По ID / Промокод»: the ways to buy one game, each on its own page.
 *
 * Looks like the region switcher (`RegionPurchase`), behaves like navigation:
 * every chip is a link to its own URL, because each variant keeps its own page
 * and search copy — the promo-code page is the one search engines know. The
 * catalogue shows the main variant only (migration 0108).
 */
export async function BrandVariants({ variants, current, locale }: BrandVariantsProps) {
  const t = await getTranslations("web.store");
  return (
    <nav aria-label={t("variantTitle")} className="mb-6">
      <div className="text-tx-mute mb-3 text-sm font-semibold">{t("variantTitle")}</div>
      <div className="flex flex-wrap gap-2">
        {variants.map((v) => {
          const active = v.slug === current;
          const key = `variants.${v.code}`;
          const label = t.has(key) ? t(key) : v.code;
          const Icon = ICONS[v.code];
          return (
            <Link
              key={v.slug}
              href={pathFor(locale, brandPath(v.slug))}
              aria-current={active ? "page" : undefined}
              className={`focus-visible:ring-primary focus-visible:ring-offset-bg inline-flex min-h-[44px] items-center gap-2 rounded-full border px-4 py-2 text-[13px] font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 ${
                active
                  ? "border-primary bg-primary/10 text-foreground"
                  : "border-border bg-card text-tx-mute hover:border-border-2"
              }`}
            >
              {Icon && (
                <Icon size={16} aria-hidden className={active ? "text-primary" : undefined} />
              )}
              {label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
