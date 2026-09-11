import { useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useState } from "react";

import { ApiError } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { amendReview, submitReview } from "@/lib/reviews";

const POSITIVE = ["reviews.tagFast", "reviews.tagAsExpected", "reviews.tagAgain"] as const;
const NEGATIVE = [
  "reviews.tagSlow",
  "reviews.tagWrongAccount",
  "reviews.tagExpensive",
  "reviews.tagSupport",
] as const;

type TagKey = (typeof POSITIVE)[number] | (typeof NEGATIVE)[number];

/**
 * One-tap star rating for a delivered order, then optional chips + comment.
 */
export function RateAsk({
  orderId,
  brandSlug,
  brandName,
}: {
  orderId: string;
  brandSlug: string;
  brandName?: string | null | undefined;
}) {
  const { t } = useT();
  const qc = useQueryClient();
  const [state, setState] = useState<"idle" | "sending" | "done" | "already" | "error">("idle");
  const [rated, setRated] = useState(0);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<TagKey>>(new Set());
  const [extra, setExtra] = useState("");

  const title = brandName
    ? t("reviews.askTitleNamed", { brand: brandName })
    : t("reviews.askTitle");
  const tags: readonly TagKey[] = rated >= 4 ? POSITIVE : NEGATIVE;

  async function onRate(rating: number) {
    setState("sending");
    try {
      const review = await submitReview({
        order_id: orderId,
        brand_slug: brandSlug,
        rating,
      });
      setReviewId(review.id);
      setRated(rating);
      setState("done");
      void qc.invalidateQueries({ queryKey: ["my-reviews"] });
      void qc.invalidateQueries({ queryKey: ["review-pending-ask"] });
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "already" : "error");
    }
  }

  function pushAmend(nextTags: Set<TagKey>, nextExtra: string) {
    if (!reviewId) return;
    const labels = [...nextTags].map((k) => t(k));
    const body = [...labels, nextExtra.trim()].filter(Boolean).join(". ");
    if (body) void amendReview(reviewId, body);
  }

  if (state === "already") return null;

  if (state === "done") {
    return (
      <div className="rounded-xl border border-white/10 p-3">
        <p className="text-primary text-sm font-semibold">{t("reviews.thanks")}</p>
        <p className="mt-1 text-[11px] text-white/50">{t("reviews.followUp")}</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {tags.map((key) => {
            const on = picked.has(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  const next = new Set(picked);
                  if (on) next.delete(key);
                  else next.add(key);
                  setPicked(next);
                  pushAmend(next, extra);
                }}
                className={
                  on
                    ? "bg-primary text-primary-foreground rounded-full px-2.5 py-1 text-[11px] font-semibold"
                    : "rounded-full border border-white/15 px-2.5 py-1 text-[11px] text-white/60"
                }
              >
                {t(key)}
              </button>
            );
          })}
        </div>
        <textarea
          value={extra}
          onChange={(e) => {
            setExtra(e.target.value.slice(0, 2000));
          }}
          onBlur={() => {
            pushAmend(picked, extra);
          }}
          placeholder={t("reviews.commentPlaceholder")}
          rows={2}
          className="mt-2 w-full resize-none rounded-lg border border-white/10 bg-transparent px-2 py-1.5 text-sm text-white outline-none"
        />
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/10 p-3">
      <p className="text-sm font-semibold text-white">{title}</p>
      <p className="mt-1 text-[11px] text-white/50">{t("reviews.askHint")}</p>
      <div className="mt-2 flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            aria-label={String(n)}
            disabled={state === "sending"}
            onClick={() => {
              void onRate(n);
            }}
          >
            <Star
              size={26}
              className={n <= rated ? "fill-amber-400 text-amber-400" : "text-white/25"}
            />
          </button>
        ))}
      </div>
      {state === "error" && <p className="mt-1 text-xs text-red-400">{t("reviews.error")}</p>}
    </div>
  );
}
