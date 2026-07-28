"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
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

  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [body, setBody] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "done" | "already" | "error">("idle");

  if (!user || !orderId) return null;
  if (state === "done") {
    return <p className="text-primary mt-6 text-[14px] font-semibold">{t("thanks")}</p>;
  }
  if (state === "already") {
    return <p className="text-tx-mute mt-6 text-[14px]">{t("alreadyReviewed")}</p>;
  }

  async function onSubmit(e: React.SyntheticEvent) {
    e.preventDefault();
    if (rating < 1 || !orderId) return;
    setState("sending");
    try {
      await submitReview({
        order_id: orderId,
        brand_slug: brandSlug,
        rating,
        ...(body.trim() ? { body: body.trim() } : {}),
      });
      setState("done");
      // Refresh "my reviews" so the account CTA and the delivered modal stop
      // offering to rate an order that's now reviewed.
      void qc.invalidateQueries({ queryKey: ["my-reviews"] });
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "already" : "error");
    }
  }

  const active = hover || rating;
  return (
    <form onSubmit={onSubmit} className="border-border bg-card mt-8 rounded-2xl border p-5">
      <p className="text-[14px] font-semibold">{t("formTitle")}</p>
      <div className="mt-3">
        <div className="text-tx-mute mb-1.5 text-[12px]">{t("ratingLabel")}</div>
        <div className="flex gap-1">
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              aria-label={String(n)}
              onClick={() => {
                setRating(n);
              }}
              onMouseEnter={() => {
                setHover(n);
              }}
              onMouseLeave={() => {
                setHover(0);
              }}
              className="p-0.5"
            >
              <Star size={26} className={n <= active ? "fill-gold text-gold" : "text-white/25"} />
            </button>
          ))}
        </div>
      </div>
      <label className="mt-4 block">
        <span className="text-tx-mute mb-1.5 block text-[12px]">{t("commentLabel")}</span>
        <textarea
          value={body}
          onChange={(e) => {
            setBody(e.target.value.slice(0, 2000));
          }}
          rows={3}
          className="border-border bg-background focus-visible:border-primary w-full resize-none rounded-xl border px-3 py-2 text-[14px] outline-none"
        />
      </label>
      {state === "error" && <p className="mt-2 text-[13px] text-red-400">{t("error")}</p>}
      <button
        type="submit"
        disabled={rating < 1 || state === "sending"}
        className={buttonStyles({ size: "sm", className: "mt-4 disabled:opacity-50" })}
      >
        {state === "sending" ? t("submitting") : t("submit")}
      </button>
    </form>
  );
}
