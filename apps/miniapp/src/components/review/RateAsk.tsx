import { useQueryClient } from "@tanstack/react-query";
import { reviewDraftHasChip, reviewFollowUp, toggleChipInReviewDraft } from "@yupay/utils";
import { Star } from "lucide-react";
import { useEffect, useState } from "react";

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

/** A review of this order that already exists — from `GET /reviews/mine`. */
export interface ExistingReview {
  id: string;
  rating: number;
  body: string | null;
  /** Whether `PATCH /reviews/{id}` would still accept a body. Server-computed. */
  can_add_text: boolean;
}

/**
 * One-tap star rating for a delivered order, then optional chips + comment.
 * Chips write into the textarea; PATCH runs only from Submit.
 *
 * **The comment step must survive the rating.** Posting a star makes this
 * order "already reviewed", and every surface that renders this component also
 * knows that fact — so a caller that hides the component once it is true tears
 * the follow-up out of the DOM in the same tick the follow-up appears. That
 * was live on three surfaces (both order pages and the web order list) and is
 * why production had 27 star-only reviews against a single edit ever. Callers
 * now pass what they know as `existing` instead of using it to unmount this:
 * a review that exists is a reason to *ask for the words*, not to go quiet.
 */
export function RateAsk({
  orderId,
  brandSlug,
  brandName,
  existing,
  onRated,
  onFinished,
}: {
  orderId: string;
  brandSlug: string;
  brandName?: string | null | undefined;
  existing?: ExistingReview | null | undefined;
  onRated?: (() => void) | undefined;
  onFinished?: (() => void) | undefined;
}) {
  const { t } = useT();
  const qc = useQueryClient();
  const [state, setState] = useState<"idle" | "sending" | "conflict" | "error">("idle");
  const [review, setReview] = useState<ExistingReview | null>(existing ?? null);
  const [tapped, setTapped] = useState(0);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [amendFailed, setAmendFailed] = useState(false);

  // `my-reviews` usually resolves after the first paint, so a review this
  // order already has arrives as a prop change rather than an initial value.
  // Adopt it — but never over a review this component just created, whose
  // `can_add_text` is true by construction and whose follow-up is on screen.
  useEffect(() => {
    if (existing && review === null) setReview(existing);
  }, [existing, review]);

  const title = brandName
    ? t("reviews.askTitleNamed", { brand: brandName })
    : t("reviews.askTitle");
  const rating = review?.rating ?? 0;
  const tags: readonly TagKey[] = rating >= 4 ? POSITIVE : NEGATIVE;
  // One rule, shared with the web surface — see `reviewFollowUp`.
  const wantsWords = !confirmed && reviewFollowUp(review) === "words";

  async function onRate(value: number) {
    setTapped(value);
    setState("sending");
    try {
      const created = await submitReview({
        order_id: orderId,
        brand_slug: brandSlug,
        rating: value,
      });
      setReview({ id: created.id, rating: value, body: null, can_add_text: true });
      setState("idle");
      onRated?.();
      void qc.invalidateQueries({ queryKey: ["my-reviews"] });
      void qc.invalidateQueries({ queryKey: ["review-pending-ask"] });
    } catch (err) {
      setTapped(0);
      if (err instanceof ApiError && err.status === 409) {
        // Rated already, on another surface or in an earlier session. We do
        // not have the row — ask for it, and the effect above will adopt it
        // and offer the comment step rather than leaving a dead end.
        setState("conflict");
        void qc.invalidateQueries({ queryKey: ["my-reviews"] });
        return;
      }
      setState("error");
    }
  }

  async function submitComment(): Promise<void> {
    const body = draft.trim();
    if (body) {
      if (!review) return;
      setSaving(true);
      setAmendFailed(false);
      try {
        await amendReview(review.id, body);
        setReview({ ...review, body });
        void qc.invalidateQueries({ queryKey: ["my-reviews"] });
      } catch {
        setAmendFailed(true);
        return;
      } finally {
        setSaving(false);
      }
    }
    setConfirmed(true);
  }

  if (wantsWords && review) {
    return (
      <div className="rounded-xl border border-white/10 p-3">
        <StarRow value={rating} />
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

  if (review !== null) {
    return (
      <div className="rounded-xl border border-white/10 p-3">
        <StarRow value={rating} />
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
      {state === "conflict" && <p className="mt-1 text-xs text-white/50">{t("reviews.already")}</p>}
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
