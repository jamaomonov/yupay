"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef } from "react";

import { ReviewAsk } from "./ReviewAsk";

import { useAuth } from "@/lib/auth";

/**
 * Eligible-buyer review form, shown on the brand page when the user arrived
 * from their order history (`?order=<id>`) and is logged in. The order's
 * eligibility is enforced server-side; a repeat submit returns 409.
 */
export function WriteReviewPanel({
  brandSlug,
  brandName,
}: {
  brandSlug: string;
  brandName?: string | null;
}) {
  const { user } = useAuth();
  const orderId = useSearchParams().get("order");
  const scrolledRef = useRef(false);

  useEffect(() => {
    if (!user || !orderId || scrolledRef.current) return;
    scrolledRef.current = true;
    document.getElementById("reviews")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [user, orderId]);

  if (!user || !orderId) return null;

  return (
    <ReviewAsk
      className="mt-8"
      orderId={orderId}
      brandSlug={brandSlug}
      brandName={brandName}
    />
  );
}
