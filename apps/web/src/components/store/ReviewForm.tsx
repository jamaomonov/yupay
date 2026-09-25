"use client";

import { Star } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";

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
  /** Nothing left to write: the review already has a body, or its window for
   *  one has closed. Shows the thanks state instead of the comment box, so a
   *  returning reviewer is never handed an input that cannot save. */
  settled?: boolean | undefined;
}

/**
 * One-tap star rating, then an optional comment. Owns input state; the
 * parent owns idle|sending|done|already|error and the actual HTTP calls.
 *
 * Nothing is sent until the buyer taps Submit — blur must not race a
 * catch-up dialog closing.
 *
 * There used to be a row of canned phrases ("Быстро", "Как обещали",
 * "Куплю ещё") that one tap wrote into the comment. Removed 2026-09-25: most
 * buyers tapped them instead of writing, so the brand page filled with
 * identical reviews that told the next buyer nothing.
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
  settled = false,
}: ReviewFormProps) {
  const t = useTranslations("web.brandReviews");
  const [hover, setHover] = useState(0);
  const [tapped, setTapped] = useState(0);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const title = brandName ? t("askTitleNamed", { brand: brandName }) : t("askTitle");
  const frame = variant === "card" ? "border-border bg-card rounded-2xl border p-5" : "";
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

  if (rated !== undefined && rated >= 1 && (confirmed || settled)) {
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
