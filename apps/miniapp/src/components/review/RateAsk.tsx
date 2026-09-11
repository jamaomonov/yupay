import { useQueryClient } from "@tanstack/react-query";
import { reviewDraftHasChip, toggleChipInReviewDraft } from "@yupay/utils";
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
 * Chips write into the textarea; PATCH runs only from Submit.
 */
export function RateAsk({
  orderId,
  brandSlug,
  brandName,
  onRated,
  onFinished,
}: {
  orderId: string;
  brandSlug: string;
  brandName?: string | null | undefined;
  onRated?: (() => void) | undefined;
  onFinished?: (() => void) | undefined;
}) {
  const { t } = useT();
  const qc = useQueryClient();
  const [state, setState] = useState<"idle" | "sending" | "done" | "already" | "error">("idle");
  const [rated, setRated] = useState(0);
  const [tapped, setTapped] = useState(0);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [amendFailed, setAmendFailed] = useState(false);

  const title = brandName
    ? t("reviews.askTitleNamed", { brand: brandName })
    : t("reviews.askTitle");
  const tags: readonly TagKey[] = rated >= 4 ? POSITIVE : NEGATIVE;

  async function onRate(rating: number) {
    setTapped(rating);
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
      onRated?.();
      void qc.invalidateQueries({ queryKey: ["my-reviews"] });
      void qc.invalidateQueries({ queryKey: ["review-pending-ask"] });
    } catch (err) {
      setTapped(0);
      setState(err instanceof ApiError && err.status === 409 ? "already" : "error");
    }
  }

  async function submitComment(): Promise<void> {
    const body = draft.trim();
    if (body) {
      if (!reviewId) return;
      setSaving(true);
      setAmendFailed(false);
      try {
        await amendReview(reviewId, body);
      } catch {
        setAmendFailed(true);
        return;
      } finally {
        setSaving(false);
      }
    }
    setConfirmed(true);
  }

  if (state === "already") return null;

  if (state === "done" && confirmed) {
    return (
      <div className="rounded-xl border border-white/10 p-3">
        <StarRow value={rated} />
        <p className="text-primary mt-2 text-sm font-semibold">{t("reviews.thanks")}</p>
        <p className="mt-1 text-[11px] text-white/50">{t("reviews.thanksBody")}</p>
        {onFinished ? (
          <button
            type="button"
            onClick={onFinished}
            className="bg-primary text-primary-foreground mt-3 w-full rounded-lg py-2 text-sm font-semibold"
          >
            {t("reviews.done")}
          </button>
        ) : null}
      </div>
    );
  }

  if (state === "done") {
    return (
      <div className="rounded-xl border border-white/10 p-3">
        <StarRow value={rated} />
        <p className="text-primary mt-2 text-sm font-semibold">{t("reviews.thanksRating")}</p>
        <p className="mt-1 text-[11px] text-white/50">{t("reviews.followUp")}</p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {tags.map((key) => {
            const label = t(key);
            const on = reviewDraftHasChip(draft, label);
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setDraft(toggleChipInReviewDraft(draft, label));
                }}
                className={
                  on
                    ? "bg-primary text-primary-foreground rounded-full px-2.5 py-1 text-[11px] font-semibold"
                    : "rounded-full border border-white/15 px-2.5 py-1 text-[11px] text-white/60"
                }
              >
                {label}
              </button>
            );
          })}
        </div>
        <textarea
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value.slice(0, 2000));
          }}
          placeholder={t("reviews.commentPlaceholder")}
          rows={2}
          className="mt-2 w-full resize-none rounded-lg border border-white/10 bg-transparent px-2 py-1.5 text-sm text-white outline-none"
        />
        {amendFailed && <p className="mt-1 text-xs text-red-400">{t("reviews.error")}</p>}
        <button
          type="button"
          disabled={saving}
          onClick={() => {
            void submitComment();
          }}
          className="bg-primary text-primary-foreground mt-2 w-full rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
        >
          {saving ? t("reviews.submitting") : t("reviews.submit")}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => {
            setConfirmed(true);
          }}
          className="mt-1 w-full py-1.5 text-sm text-white/50"
        >
          {t("reviews.skipComment")}
        </button>
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
              className={n <= tapped ? "fill-amber-400 text-amber-400" : "text-white/25"}
            />
          </button>
        ))}
      </div>
      {state === "error" && <p className="mt-1 text-xs text-red-400">{t("reviews.error")}</p>}
    </div>
  );
}

function StarRow({ value }: { value: number }) {
  return (
    <div className="flex gap-1" aria-hidden="true">
      {[1, 2, 3, 4, 5].map((n) => (
        <Star
          key={n}
          size={22}
          className={n <= value ? "fill-amber-400 text-amber-400" : "text-white/25"}
        />
      ))}
    </div>
  );
}
