import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Star, X } from "lucide-react";
import { useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { getBrandReviews, submitReview, type ReviewPage } from "@/lib/reviews";
import { useOverlay } from "@/store/useOverlay";

function StarRow({ value, size = 14 }: { value: number; size?: number }) {
  const filled = Math.round(value);
  return (
    <span className="inline-flex gap-[1px]" aria-label={`${value.toFixed(1)} / 5`}>
      {[1, 2, 3, 4, 5].map((n) => (
        <Star
          key={n}
          size={size}
          className={n <= filled ? "fill-amber-400 text-amber-400" : "text-white/20"}
        />
      ))}
    </span>
  );
}

/**
 * Bottom-sheet with a brand's rating summary + review list. When opened from an
 * order context (`formOrderId`) and the user is signed in, it also shows a
 * submit form; a repeat submit is rejected server-side (409 → "already rated").
 */
export function ReviewsSheet({
  brandSlug,
  formOrderId,
  onClose,
}: {
  brandSlug: string;
  formOrderId?: string;
  onClose: () => void;
}) {
  const { t, tn } = useT();
  const me = useMe();
  const qc = useQueryClient();

  // Hide the fixed bottom nav while this sheet is up — otherwise it paints over
  // the sheet (both are z-50; the nav is later in the DOM).
  const openOverlay = useOverlay((s) => s.open);
  const closeOverlay = useOverlay((s) => s.close);
  useEffect(() => {
    openOverlay();
    return closeOverlay;
  }, [openOverlay, closeOverlay]);
  const reviews = useQuery<ReviewPage>({
    queryKey: ["reviews", brandSlug],
    queryFn: () => getBrandReviews(brandSlug),
  });

  const [rating, setRating] = useState(0);
  const [body, setBody] = useState("");
  const [state, setState] = useState<"idle" | "sending" | "done" | "already" | "error">("idle");

  const canWrite = Boolean(formOrderId) && Boolean(me.data);

  async function onSubmit() {
    if (rating < 1 || !formOrderId) return;
    setState("sending");
    try {
      await submitReview({
        order_id: formOrderId,
        brand_slug: brandSlug,
        rating,
        ...(body.trim() ? { body: body.trim() } : {}),
      });
      setState("done");
      await reviews.refetch();
      // Refresh "my reviews" so the order-details / History rate CTAs update.
      void qc.invalidateQueries({ queryKey: ["my-reviews"] });
    } catch (err) {
      setState(err instanceof ApiError && err.status === 409 ? "already" : "error");
    }
  }

  const stats = reviews.data?.stats;

  return (
    <div className="fixed inset-0 z-50 flex items-end" role="dialog" aria-modal="true">
      <button aria-label="close" className="absolute inset-0 bg-black/60" onClick={onClose} />
      <div className="relative max-h-[80vh] w-full overflow-y-auto rounded-t-2xl bg-[hsl(var(--card))] p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-base font-bold text-white">{t("reviews.title")}</h2>
          <button aria-label="close" onClick={onClose} className="text-white/50">
            <X size={20} />
          </button>
        </div>

        {stats && stats.count > 0 ? (
          <div className="mb-4 flex items-center gap-3">
            <span className="text-2xl font-extrabold text-white">{stats.avg.toFixed(1)}</span>
            <div className="flex flex-col">
              <StarRow value={stats.avg} />
              <span className="text-[11px] text-white/50">{tn("reviews.count", stats.count)}</span>
            </div>
          </div>
        ) : (
          <p className="mb-4 text-sm text-white/50">{t("reviews.empty")}</p>
        )}

        {canWrite && state !== "done" && state !== "already" && (
          <div className="mb-4 rounded-xl border border-white/10 p-3">
            <div className="mb-2 flex gap-1">
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  aria-label={String(n)}
                  onClick={() => {
                    setRating(n);
                  }}
                >
                  <Star
                    size={24}
                    className={n <= rating ? "fill-amber-400 text-amber-400" : "text-white/25"}
                  />
                </button>
              ))}
            </div>
            <textarea
              value={body}
              onChange={(e) => {
                setBody(e.target.value.slice(0, 2000));
              }}
              placeholder={t("reviews.commentPlaceholder")}
              rows={2}
              className="w-full resize-none rounded-lg border border-white/10 bg-transparent px-2 py-1.5 text-sm text-white outline-none"
            />
            {state === "error" && <p className="mt-1 text-xs text-red-400">{t("reviews.error")}</p>}
            <button
              type="button"
              disabled={rating < 1 || state === "sending"}
              onClick={() => {
                void onSubmit();
              }}
              className="bg-primary text-primary-foreground mt-2 w-full rounded-lg py-2 text-sm font-semibold disabled:opacity-50"
            >
              {t("reviews.submit")}
            </button>
          </div>
        )}
        {state === "done" && (
          <p className="text-primary mb-4 text-sm font-semibold">{t("reviews.thanks")}</p>
        )}
        {state === "already" && (
          <p className="mb-4 text-sm text-white/60">{t("reviews.already")}</p>
        )}

        <ul className="flex flex-col gap-3">
          {(reviews.data?.items ?? []).map((r) => (
            <li key={r.id} className="border-b border-white/10 pb-3 last:border-b-0">
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-white">
                  {r.author_name ?? t("reviews.anonymous")}
                </span>
                <StarRow value={r.rating} size={12} />
              </div>
              {r.body && <p className="mt-1 text-sm text-white/70">{r.body}</p>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
