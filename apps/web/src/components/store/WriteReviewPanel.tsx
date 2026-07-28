"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { ReviewForm } from "./ReviewForm";

import { useAuth } from "@/lib/auth";
import { ApiError } from "@/lib/client";
import { submitReview } from "@/lib/reviews";

/**
 * Eligible-buyer review form, shown on the brand page when the user arrived
 * from their order history (`?order=<id>`) and is logged in. The order's
 * eligibility (delivered, contains this brand, not already reviewed) is enforced
 * server-side; a repeat submit returns 409 → "already reviewed".
 */
export function WriteReviewPanel({ brandSlug }: { brandSlug: string }) {
  const t = useTranslations("web.brandReviews");
  const { user } = useAuth();
  const qc = useQueryClient();
  const orderId = useSearchParams().get("order");

  const [state, setState] = useState<"idle" | "sending" | "done" | "already" | "error">("idle");

  if (!user || !orderId) return null;
  if (state === "done") {
    return <p className="text-primary mt-6 text-[14px] font-semibold">{t("thanks")}</p>;
  }
  if (state === "already") {
    return <p className="text-tx-mute mt-6 text-[14px]">{t("alreadyReviewed")}</p>;
  }

  async function handleSubmit(rating: number, body: string) {
    if (!orderId) return;
    setState("sending");
    try {
      await submitReview({
        order_id: orderId,
        brand_slug: brandSlug,
        rating,
        ...(body ? { body } : {}),
      });
      setState("done");
      // Refresh "my reviews" so the account CTA and the delivered modal stop
      // offering to rate an order that's now reviewed.
      void qc.invalidateQueries({ queryKey: ["my-reviews"] });
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "already" : "error");
    }
  }

  return (
    <ReviewForm
      className="mt-8"
      submitting={state === "sending"}
      showError={state === "error"}
      onSubmit={handleSubmit}
    />
  );
}
