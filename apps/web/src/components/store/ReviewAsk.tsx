"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ReviewForm } from "./ReviewForm";

import { ApiError } from "@/lib/client";
import { amendReview, submitReview } from "@/lib/reviews";

/**
 * One-tap review for a delivered order. Parents only gate eligibility; this
 * owns the POST (star) + PATCH (chips/comment) and the follow-up UI.
 */
export function ReviewAsk({
  orderId,
  brandSlug,
  brandName,
  guestEmail,
  variant = "card",
  className,
  onRated,
  onFinished,
}: {
  orderId: string;
  brandSlug: string;
  brandName?: string | null | undefined;
  guestEmail?: string | undefined;
  variant?: "card" | "bare";
  className?: string | undefined;
  /** Fired after the rating POST succeeds — catch-up keeps the dialog open. */
  onRated?: (() => void) | undefined;
  /** Fired from the follow-up "Done" button after comment submit or skip. */
  onFinished?: (() => void) | undefined;
}) {
  const qc = useQueryClient();
  const [state, setState] = useState<"idle" | "sending" | "done" | "already" | "error">("idle");
  const [rated, setRated] = useState(0);
  const [reviewId, setReviewId] = useState<string | null>(null);
  const guest = guestEmail ? { guestEmail } : {};

  async function handleSubmit(rating: number) {
    setState("sending");
    try {
      const review = await submitReview(
        { order_id: orderId, brand_slug: brandSlug, rating },
        guest,
      );
      setReviewId(review.id);
      setRated(rating);
      setState("done");
      onRated?.();
      void qc.invalidateQueries({ queryKey: ["my-reviews"] });
      void qc.invalidateQueries({ queryKey: ["review-pending-ask"] });
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "already" : "error");
    }
  }

  async function handleAmend(body: string) {
    if (!reviewId) return;
    try {
      await amendReview(reviewId, body, guest);
      setState("done");
    } catch (err) {
      setState("error");
      throw err;
    }
  }

  if (state === "already") {
    return null;
  }

  return (
    <ReviewForm
      className={className}
      variant={variant}
      brandName={brandName}
      submitting={state === "sending"}
      showError={state === "error"}
      rated={rated >= 1 ? rated : undefined}
      onSubmit={(rating) => {
        void handleSubmit(rating);
      }}
      onAmend={handleAmend}
      onFinished={onFinished}
    />
  );
}
