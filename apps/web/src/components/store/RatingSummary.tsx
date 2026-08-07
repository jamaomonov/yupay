import { MessageSquareText } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Stars } from "./Stars";

import type { ReviewStats } from "@/lib/reviews";

/**
 * Aggregate rating block: big average, star row, count, and a 5→1 histogram.
 * Server component (no client JS). Renders an empty state when count is 0.
 */
export async function RatingSummary({ stats }: { stats: ReviewStats }) {
  const t = await getTranslations("web.brandReviews");

  if (stats.count === 0) {
    return (
      <div className="border-border/70 flex flex-col items-center gap-2 rounded-2xl border border-dashed px-6 py-10 text-center">
        <MessageSquareText className="text-tx-dim" size={26} aria-hidden="true" />
        <p className="text-foreground text-[15px] font-semibold">{t("empty")}</p>
        <p className="text-tx-mute max-w-[280px] text-[13px] leading-relaxed">{t("emptyHint")}</p>
      </div>
    );
  }

  const rows = [5, 4, 3, 2, 1].map((star) => ({
    star,
    n: stats.dist[String(star)] ?? 0,
  }));

  return (
    <div className="flex flex-col gap-5 sm:flex-row sm:items-center sm:gap-10">
      <div className="flex flex-col items-center gap-1.5">
        <div className="font-display text-[42px] font-extrabold leading-none">
          {stats.avg.toFixed(1)}
        </div>
        <Stars value={stats.avg} size={16} label={t("ratingAria", { value: stats.avg })} />
        <div className="text-tx-mute text-[12px]">{t("count", { count: stats.count })}</div>
      </div>
      <div className="flex min-w-[200px] max-w-[340px] flex-1 flex-col gap-1.5">
        {rows.map(({ star, n }) => (
          <div key={star} className="text-tx-mute flex items-center gap-2 text-[11px]">
            <span className="w-3 text-right tabular-nums">{star}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/10">
              <div
                className="bg-gold h-full rounded-full"
                style={{ width: `${String(stats.count ? (n / stats.count) * 100 : 0)}%` }}
              />
            </div>
            <span className="w-6 text-right tabular-nums">{n}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
