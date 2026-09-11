"use client";

import { useQuery } from "@tanstack/react-query";

import { ReviewAsk } from "@/components/store/ReviewAsk";
import { getReviewEligibility } from "@/lib/reviews";

/**
 * Inline review form for a GUEST on their order-status page. A guest gets no
 * global delivered modal (the realtime channel is user-only), so the review
 * ask lives here.
 */
export function GuestReviewPanel({
  orderId,
  email,
  brandName,
}: {
  orderId: string;
  email: string;
  brandName?: string | null;
}) {
  const eligibility = useQuery({
    queryKey: ["review-eligibility", orderId],
    queryFn: () => getReviewEligibility(orderId, { guestEmail: email }),
  });

  const e = eligibility.data;
  if (!e || !e.delivered || !e.brand_slug || e.already_reviewed) return null;

  return (
    <ReviewAsk
      className="mt-6"
      orderId={orderId}
      brandSlug={e.brand_slug}
      brandName={brandName}
      guestEmail={email}
    />
  );
}
