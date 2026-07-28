"use client";

import { useQuery } from "@tanstack/react-query";
import { Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { buttonStyles } from "@/lib/button";
import { ApiError } from "@/lib/client";
import { getReviewEligibility, submitReview } from "@/lib/reviews";

/**
 * Inline review form for a GUEST on their order-status page. A guest gets no
 * global delivered modal (the realtime channel is user-only), so the review
 * ask lives here, using the email the page already holds — no PII in any URL.
 * Eligibility (delivered + not already reviewed) is checked server-side.
 */
export function GuestReviewPanel({ orderId, email }: { orderId: string; email: string }) {
  const t = useTranslations("web.brandReviews");
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [body, setBody] = useState("");
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
  async function onSubmit(ev: React.SyntheticEvent) {
    ev.preventDefault();
    if (rating < 1) return;
    setState("sending");
    try {
      await submitReview(
        {
          order_id: orderId,
          brand_slug: brandSlug,
          rating,
          ...(body.trim() ? { body: body.trim() } : {}),
        },
        { guestEmail: email },
      );
      setState("done");
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "already" : "error");
    }
  }

  const active = hover || rating;
  return (
    <form onSubmit={onSubmit} className="border-border bg-card mt-6 rounded-2xl border p-5">
      <p className="text-sm font-semibold">{t("formTitle")}</p>
      <div className="mt-3">
        <div className="text-tx-mute mb-1.5 text-xs">{t("ratingLabel")}</div>
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
        <span className="text-tx-mute mb-1.5 block text-xs">{t("commentLabel")}</span>
        <textarea
          value={body}
          onChange={(ev) => {
            setBody(ev.target.value.slice(0, 2000));
          }}
          rows={3}
          className="border-border bg-background focus-visible:border-primary w-full resize-none rounded-xl border px-3 py-2 text-sm outline-none"
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
