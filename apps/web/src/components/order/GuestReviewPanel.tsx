"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ReviewForm } from "@/components/store/ReviewForm";
import { ApiError } from "@/lib/client";
import { getReviewEligibility, submitReview } from "@/lib/reviews";

/**
 * Inline review form for a GUEST on their order-status page. A guest gets no
 * global delivered modal (the realtime channel is user-only), so the review
 * ask lives here. It receives the email as a prop rather than reading the
 * URL itself — the page-level component owns that concern.
 * Eligibility (delivered + not already reviewed) is checked server-side.
 */
export function GuestReviewPanel({ orderId, email }: { orderId: string; email: string }) {
  const t = useTranslations("web.brandReviews");
  const [state, setState] = useState<"idle" | "sending" | "done" | "already" | "error">("idle");

  const eligibility = useQuery({
    queryKey: ["review-eligibility", orderId],
    queryFn: () => getReviewEligibility(orderId, { guestEmail: email }),
  });

  const e = eligibility.data;
  if (!e || !e.delivered || !e.brand_slug || e.already_reviewed) return null;
  if (state === "done") {
    return <p className="text-primary mt-4 text-sm font-semibold">{t("thanks")}</p>;
  }
  if (state === "already") {
    return <p className="text-tx-mute mt-4 text-sm">{t("alreadyReviewed")}</p>;
  }

  const brandSlug = e.brand_slug;
  async function handleSubmit(rating: number, body: string) {
    setState("sending");
    try {
      await submitReview(
        {
          order_id: orderId,
          brand_slug: brandSlug,
          rating,
          ...(body ? { body } : {}),
        },
        { guestEmail: email },
      );
      setState("done");
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "already" : "error");
    }
  }

  return (
    <ReviewForm
      className="mt-6"
      submitting={state === "sending"}
      showError={state === "error"}
      onSubmit={handleSubmit}
    />
  );
}
