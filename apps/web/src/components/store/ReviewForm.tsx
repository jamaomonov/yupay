"use client";

import { Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

const POSITIVE_TAGS = ["tagFast", "tagAsExpected", "tagAgain"] as const;
const NEGATIVE_TAGS = ["tagSlow", "tagWrongAccount", "tagExpensive", "tagSupport"] as const;

type TagKey = (typeof POSITIVE_TAGS)[number] | (typeof NEGATIVE_TAGS)[number];

export interface ReviewFormProps {
  /** Called with the chosen rating (1–5) the moment a star is tapped. */
  onSubmit: (rating: number) => void;
  /** Called with the composed comment (chips + extra text) after a rating. */
  onAmend?: ((body: string) => void) | undefined;
  submitting: boolean;
  showError: boolean;
  className?: string | undefined;
  variant?: "card" | "bare";
  brandName?: string | null | undefined;
  /** Set after a successful rating POST — switches the form into follow-up. */
  rated?: number | undefined;
}

/**
 * One-tap star rating, then optional chips + comment. Owns input state; the
 * parent owns idle|sending|done|already|error and the actual HTTP calls.
 */
export function ReviewForm({
  onSubmit,
  onAmend,
  submitting,
  showError,
  className,
  variant = "card",
  brandName,
  rated,
}: ReviewFormProps) {
  const t = useTranslations("web.brandReviews");
  const [hover, setHover] = useState(0);
  const [picked, setPicked] = useState<Set<TagKey>>(new Set());
  const [extra, setExtra] = useState("");

  const title = brandName ? t("askTitleNamed", { brand: brandName }) : t("askTitle");
  const frame = variant === "card" ? "border-border bg-card rounded-2xl border p-5" : "";
  const tags: readonly TagKey[] = (rated ?? 0) >= 4 ? POSITIVE_TAGS : NEGATIVE_TAGS;

  function pushAmend(nextTags: Set<TagKey>, nextExtra: string) {
    if (!onAmend) return;
    const labels = [...nextTags].map((k) => t(k));
    const body = [...labels, nextExtra.trim()].filter(Boolean).join(". ");
    if (body) onAmend(body);
  }

  if (rated !== undefined && rated >= 1) {
    return (
      <div className={`${frame} ${className ?? ""}`}>
        <p className="text-primary text-sm font-semibold">{t("thanks")}</p>
        <p className="text-tx-mute mt-1 text-xs">{t("followUp")}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {tags.map((key) => {
            const on = picked.has(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  const next = new Set(picked);
                  if (on) next.delete(key);
                  else next.add(key);
                  setPicked(next);
                  pushAmend(next, extra);
                }}
                className={
                  on
                    ? "bg-primary text-primary-foreground rounded-full px-2.5 py-1 text-xs font-semibold"
                    : "border-border text-tx-mute rounded-full border px-2.5 py-1 text-xs"
                }
              >
                {t(key)}
              </button>
            );
          })}
        </div>
        <label className="mt-3 block">
          <span className="sr-only">{t("commentLabel")}</span>
          <textarea
            value={extra}
            onChange={(ev) => {
              setExtra(ev.target.value.slice(0, 2000));
            }}
            onBlur={() => {
              pushAmend(picked, extra);
            }}
            rows={2}
            className="border-border bg-background focus-visible:border-primary w-full resize-none rounded-xl border px-3 py-2 text-sm outline-none"
          />
        </label>
        {showError && <p className="mt-2 text-[13px] text-red-400">{t("error")}</p>}
      </div>
    );
  }

  const active = hover;
  return (
    <div className={`${frame} ${className ?? ""}`}>
      <p className="text-sm font-semibold">{title}</p>
      <p className="text-tx-mute mt-1 text-xs">{t("askHint")}</p>
      <div className="mt-3 flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            type="button"
            aria-label={String(n)}
            disabled={submitting}
            onClick={() => {
              onSubmit(n);
            }}
            onMouseEnter={() => {
              setHover(n);
            }}
            onMouseLeave={() => {
              setHover(0);
            }}
            className="p-0.5 disabled:opacity-50"
          >
            <Star size={26} className={n <= active ? "fill-gold text-gold" : "text-white/25"} />
          </button>
        ))}
      </div>
      {showError && <p className="mt-2 text-[13px] text-red-400">{t("error")}</p>}
    </div>
  );
}
