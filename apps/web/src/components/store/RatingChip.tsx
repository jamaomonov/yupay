import { getTranslations } from "next-intl/server";

import { Stars } from "./Stars";

import type { ReviewStats } from "@/lib/reviews";

/**
 * Compact rating pill for the brand-page hero — surfaces real social proof at
 * the decision point (top of the page), not just in the reviews block at the
 * bottom. Strictly gated on real data: renders nothing when `count === 0`, so
 * it stays absent until genuine reviews exist and never fabricates a rating.
 * Reuses the reviews stats the page already fetched (no extra request).
 */
export async function RatingChip({ stats }: { stats: ReviewStats }) {
  if (stats.count === 0) return null;
  const t = await getTranslations("web.brandReviews");
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-white/15 bg-black/40 px-3 py-1.5 text-[12px] font-semibold text-white backdrop-blur">
      <Stars value={stats.avg} size={13} />
      <span>{stats.avg.toFixed(1)}</span>
      <span className="text-white/60">· {t("count", { count: stats.count })}</span>
    </span>
  );
}
