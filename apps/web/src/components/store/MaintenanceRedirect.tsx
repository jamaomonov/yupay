import { AlertTriangle, ArrowRight } from "lucide-react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import type { BrandRedirect } from "@/lib/catalog";

import { brandPath } from "@/lib/brand-href";
import { buttonStyles } from "@/lib/button";
import { pathFor } from "@/lib/seo";

interface MaintenanceRedirectProps {
  target: BrandRedirect;
  locale: string;
}

/**
 * A paused brand's way out: «this is not on sale now — this is».
 *
 * The page keeps its packs and copy (and the search traffic that lands on it),
 * but the API refuses its orders while the brand is in maintenance, so the
 * buyer is told up front, above the packs, where the same goods are on sale.
 * Standoff 2 promo codes → Gold by player id (2026-10-27).
 */
export async function MaintenanceRedirect({ target, locale }: MaintenanceRedirectProps) {
  const t = await getTranslations("web.store");
  return (
    <div className="mb-5 flex flex-col gap-4 rounded-2xl border border-amber-400/50 bg-amber-400/10 p-5 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex min-w-0 gap-3">
        <AlertTriangle size={20} className="mt-0.5 shrink-0 text-amber-300" aria-hidden />
        <div className="min-w-0">
          <p className="text-[15px] font-semibold">{t("maintenanceRedirectTitle")}</p>
          <p className="text-tx-mute mt-1 text-[14px] leading-relaxed">
            {target.short_description ?? t("maintenanceRedirectBody", { name: target.name })}
          </p>
        </div>
      </div>
      <Link
        href={pathFor(locale, brandPath(target.slug))}
        className={buttonStyles({ className: "shrink-0" })}
      >
        {t("maintenanceRedirectGo", { name: target.name })}
        <ArrowRight size={16} aria-hidden />
      </Link>
    </div>
  );
}
