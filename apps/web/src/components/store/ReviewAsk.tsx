"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { reviewFollowUp } from "@yupay/utils";

import { ReviewForm } from "./ReviewForm";

import { ApiError } from "@/lib/client";
import { amendReview, submitReview } from "@/lib/reviews";

/** A review of this order that already exists — from `GET /reviews/mine`. */
export interface ExistingReview {
  id: string;
  rating: number;
  body: string | null;
  can_add_text: boolean;
}

/**
 * One-tap review for a delivered order. Parents only gate eligibility; this
 * owns the POST (star) + PATCH (chips/comment) and the follow-up UI.
 *
 * **A review that exists is not a reason to go quiet.** Parents used to read
 * "this order was reviewed" and unmount this component — which, because
 * posting a star is what makes that true, tore the comment step out in the
 * tick it appeared. Pass what you know as `existing` instead: a star-only
 * review still wants its words, and a finished one is worth showing back so
 * the buyer can see their review did not vanish.
 */
export function ReviewAsk({
  orderId,
  brandSlug,
  brandName,
  guestEmail,
  existing,
  hideWhenSettled = false,
  variant = "card",
  className,
  onRated,
  onFinished,
}: {
  orderId: string;
  brandSlug: string;
  brandName?: string | null | undefined;
  guestEmail?: string | undefined;
  existing?: ExistingReview | null | undefined;
  /** For lists: render nothing when this order's review is already finished. */
  hideWhenSettled?: boolean | undefined;
  variant?: "card" | "bare";
  className?: string | undefined;
  /** Fired after the rating POST succeeds — catch-up keeps the dialog open. */
  onRated?: (() => void) | undefined;
  /** Fired from the follow-up "Done" button after comment submit or skip. */
  onFinished?: (() => void) | undefined;
}) {
  const qc = useQueryClient();
  const [state, setState] = useState<"idle" | "sending" | "already" | "error">("idle");
  const [review, setReview] = useState<ExistingReview | null>(existing ?? null);
  const guest = guestEmail ? { guestEmail } : {};
  // Mount-time only. A list that renders one of these per order should not
  // carry a thanks card for every past purchase — but hiding on the *current*
  // state would yank the card away the instant the comment saves, which is the
  // bug this component exists to stop repeating.
  const [settledAtMount] = useState(() => reviewFollowUp(existing) === "settled");

  // `my-reviews` usually resolves after the first paint. Adopt what it finds,
  // but never over a review this component just created.
  useEffect(() => {
    if (existing && review === null) setReview(existing);
  }, [existing, review]);

  async function handleSubmit(rating: number) {
    setState("sending");
    try {
      const created = await submitReview(
        { order_id: orderId, brand_slug: brandSlug, rating },
        guest,
      );
      setReview({ id: created.id, rating, body: null, can_add_text: true });
      setState("idle");
      onRated?.();
      void qc.invalidateQueries({ queryKey: ["my-reviews"] });
      void qc.invalidateQueries({ queryKey: ["review-pending-ask"] });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Rated already, elsewhere or in an earlier session. Ask for the row
        // so the effect above can adopt it and offer the words; a guest has
        // no `my-reviews` to adopt from and gets the note below instead.
        setState("already");
        void qc.invalidateQueries({ queryKey: ["my-reviews"] });
        return;
      }
      setState("error");
    }
  }

  async function handleAmend(body: string) {
    if (!review) return;
    try {
      await amendReview(review.id, body, guest);
      setReview({ ...review, body });
      void qc.invalidateQueries({ queryKey: ["my-reviews"] });
    } catch (err) {
      setState("error");
      throw err;
    }
  }

  if (hideWhenSettled && settledAtMount) return null;

  if (review === null && state === "already") {
    return <AlreadyRatedNote className={className} variant={variant} />;
  }

  return (
    <ReviewForm
      className={className}
      variant={variant}
      brandName={brandName}
      submitting={state === "sending"}
      showError={state === "error"}
      rated={review ? review.rating : undefined}
      settled={reviewFollowUp(review) === "settled"}
      onSubmit={(rating) => {
        void handleSubmit(rating);
      }}
      onAmend={handleAmend}
      onFinished={onFinished}
    />
  );
}

/** The 409 fallback for an actor whose review we cannot look up (a guest). */
function AlreadyRatedNote({
  className,
  variant,
}: {
  className?: string | undefined;
  variant: "card" | "bare";
}) {
  const t = useTranslations("web.brandReviews");
  const frame = variant === "card" ? "border-border bg-card rounded-2xl border p-5" : "";
  return (
    <div className={`${frame} ${className ?? ""}`}>
      <p className="text-tx-mute text-sm">{t("alreadyReviewed")}</p>
    </div>
  );
}
