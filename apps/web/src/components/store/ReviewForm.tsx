"use client";

import { reviewDraftHasChip, toggleChipInReviewDraft } from "@yupay/utils";
import { Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

const POSITIVE_TAGS = ["tagFast", "tagAsExpected", "tagAgain"] as const;
const NEGATIVE_TAGS = ["tagSlow", "tagWrongAccount", "tagExpensive", "tagSupport"] as const;

type TagKey = (typeof POSITIVE_TAGS)[number] | (typeof NEGATIVE_TAGS)[number];

export interface ReviewFormProps {
  /** Called with the chosen rating (1–5) the moment a star is tapped. */
  onSubmit: (rating: number) => void;
  /** Called once, from the follow-up submit button, with the draft body. */
  onAmend?: ((body: string) => Promise<void> | void) | undefined;
  submitting: boolean;
  showError: boolean;
  className?: string | undefined;
  variant?: "card" | "bare";
  brandName?: string | null | undefined;
  /** Set after a successful rating POST — switches the form into follow-up. */
  rated?: number | undefined;
  /** After the comment is saved (or skipped) and the buyer taps Done. */
  onFinished?: (() => void) | undefined;
}

/**
 * One-tap star rating, then optional chips + comment. Owns input state; the
 * parent owns idle|sending|done|already|error and the actual HTTP calls.
 *
 * Chips write into the same textarea as free text (one draft, one PATCH).
 * Nothing is sent until the buyer taps Submit — blur/chip must not race a
 * catch-up dialog closing.
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
  onFinished,
}: ReviewFormProps) {
  const t = useTranslations("web.brandReviews");
  const [hover, setHover] = useState(0);
  const [tapped, setTapped] = useState(0);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const title = brandName ? t("askTitleNamed", { brand: brandName }) : t("askTitle");
  const frame = variant === "card" ? "border-border bg-card rounded-2xl border p-5" : "";
  const tags: readonly TagKey[] = (rated ?? 0) >= 4 ? POSITIVE_TAGS : NEGATIVE_TAGS;
  const filled = hover || tapped;

  async function submitComment(): Promise<void> {
    const body = draft.trim();
    if (body && onAmend) {
      setSaving(true);
      try {
        await onAmend(body);
      } catch {
        return;
      } finally {
        setSaving(false);
      }
    }
    setConfirmed(true);
  }

  if (rated !== undefined && rated >= 1 && confirmed) {
    return (
      <div className={`${frame} ${className ?? ""}`}>
        <StarRow value={rated} />
        <p className="text-primary mt-2 text-sm font-semibold">{t("thanks")}</p>
        <p className="text-tx-mute mt-1 text-xs">{t("thanksBody")}</p>
        {onFinished ? (
          <button
            type="button"
            onClick={onFinished}
            className="bg-primary text-primary-foreground mt-3 w-full rounded-xl py-2 text-sm font-semibold"
          >
            {t("done")}
          </button>
        ) : null}
      </div>
    );
  }

  if (rated !== undefined && rated >= 1) {
    return (
      <div className={`${frame} ${className ?? ""}`}>
        <StarRow value={rated} />
        <p className="text-primary mt-2 text-sm font-semibold">{t("thanksRating")}</p>
        <p className="text-tx-mute mt-1 text-xs">{t("followUp")}</p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {tags.map((key) => {
            const label = t(key);
            const on = reviewDraftHasChip(draft, label);
            return (
              <button
                key={key}
                type="button"
                onClick={() => {
                  setDraft(toggleChipInReviewDraft(draft, label));
                }}
                className={
                  on
                    ? "bg-primary text-primary-foreground rounded-full px-2.5 py-1 text-xs font-semibold"
                    : "border-border text-tx-mute rounded-full border px-2.5 py-1 text-xs"
                }
              >
                {label}
              </button>
            );
          })}
        </div>
        <label className="mt-3 block">
          <span className="sr-only">{t("commentLabel")}</span>
          <textarea
            value={draft}
            onChange={(ev) => {
              setDraft(ev.target.value.slice(0, 2000));
            }}
            placeholder={t("commentLabel")}
            rows={2}
            className="border-border bg-background focus-visible:border-primary w-full resize-none rounded-xl border px-3 py-2 text-sm outline-none"
          />
        </label>
        {showError && <p className="mt-2 text-[13px] text-red-400">{t("error")}</p>}
        <button
          type="button"
          disabled={saving}
          onClick={() => {
            void submitComment();
          }}
          className="bg-primary text-primary-foreground mt-3 w-full rounded-xl py-2 text-sm font-semibold disabled:opacity-50"
        >
          {saving ? t("submitting") : t("submit")}
        </button>
        <button
          type="button"
          disabled={saving}
          onClick={() => {
            setConfirmed(true);
          }}
          className="text-tx-mute mt-2 w-full py-1 text-sm"
        >
          {t("skipComment")}
        </button>
      </div>
    );
  }

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
              setTapped(n);
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
            <Star size={26} className={n <= filled ? "fill-gold text-gold" : "text-white/25"} />
          </button>
        ))}
      </div>
      {showError && <p className="mt-2 text-[13px] text-red-400">{t("error")}</p>}
    </div>
  );
}

function StarRow({ value }: { value: number }) {
  return (
    <div className="flex gap-1" aria-hidden="true">
      {[1, 2, 3, 4, 5].map((n) => (
        <Star key={n} size={22} className={n <= value ? "fill-gold text-gold" : "text-white/25"} />
      ))}
    </div>
  );
}
