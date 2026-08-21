"use client";

import { Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { buttonStyles } from "@/lib/button";

export interface ReviewFormProps {
  /** Called with the chosen rating (1–5) and the trimmed comment body when the
   *  form is submitted. Never invoked while `rating < 1` — the submit button
   *  is disabled and the form intercepts submit in that case too. */
  onSubmit: (rating: number, body: string) => void;
  /** True while the parent's submit request is in flight. Disables the submit
   *  button and swaps its label to the "submitting" translation. */
  submitting: boolean;
  /** True to show the inline error line below the textarea (the parent's last
   *  submit attempt failed with a non-409 error). */
  showError: boolean;
  /** Extra classes merged onto the outer `<form>` — callers differ only in
   *  their top margin (e.g. `mt-6` vs `mt-8`). */
  className?: string;
  /** `card` (default) frames the form as its own panel inside a page section.
   *  `bare` drops the frame for a host that already is one — the delivered
   *  modal, where a bordered card inside a bordered card reads as a mistake. */
  variant?: "card" | "bare";
}

/**
 * Presentational star-rating + comment form shared by GuestReviewPanel and
 * WriteReviewPanel. Owns only the input state (rating/hover/body); the
 * idle|sending|done|already|error orchestration, auth/eligibility gating, and
 * the actual submit call stay in the parent, which drives this component via
 * `submitting`/`showError` and receives the result through `onSubmit`.
 */
export function ReviewForm({
  onSubmit,
  submitting,
  showError,
  className,
  variant = "card",
}: ReviewFormProps) {
  const t = useTranslations("web.brandReviews");
  const [rating, setRating] = useState(0);
  const [hover, setHover] = useState(0);
  const [body, setBody] = useState("");

  function handleSubmit(e: React.SyntheticEvent) {
    e.preventDefault();
    if (rating < 1) return;
    onSubmit(rating, body.trim());
  }

  const active = hover || rating;
  const frame = variant === "card" ? "border-border bg-card rounded-2xl border p-5" : "";
  return (
    <form onSubmit={handleSubmit} className={`${frame} ${className ?? ""}`}>
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
      {showError && <p className="mt-2 text-[13px] text-red-400">{t("error")}</p>}
      <button
        type="submit"
        disabled={rating < 1 || submitting}
        className={buttonStyles({ size: "sm", className: "mt-4 disabled:opacity-50" })}
      >
        {submitting ? t("submitting") : t("submit")}
      </button>
    </form>
  );
}
