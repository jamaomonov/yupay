/**
 * One review, as the moderation queue shows it.
 *
 * A row, not a table cell, because the body runs from `null` to a paragraph:
 * a table either stretches every row to the longest one or clips the text to a
 * fragment nobody can moderate from. Three lines — verdict, text, provenance —
 * hold both shapes without either compromise.
 *
 * Shared by the recent feed and by a brand's expanded list. Inside a brand the
 * logo and name are dropped (`showBrand={false}`): repeating the brand on every
 * row of a block titled with that brand is noise, and the space goes to the text.
 */

import { Flag } from "lucide-react";
import { Link } from "react-router-dom";

import type { AdminReview } from "./types";

import { Badge } from "@/components/Badge";
import { CopyId } from "@/components/CopyId";
import { StatusChip } from "@/components/StatusChip";
import { Thumb } from "@/components/Thumb";

/** `★★★☆☆` — five slots always, so the rating reads as a shape rather than
 *  something to count. A bare `"★".repeat(n)` makes 3 and 4 look alike. */
function Stars({ rating }: { rating: number }) {
  const full = Math.max(0, Math.min(5, rating));
  return (
    <span className="font-mono text-sm leading-none" title={`${String(rating)} из 5`}>
      <span className="text-[var(--warning-fg)]">{"★".repeat(full)}</span>
      <span className="text-[var(--text-disabled)]">{"☆".repeat(5 - full)}</span>
      <span className="sr-only">{rating} из 5</span>
    </span>
  );
}

/** Russian plural for the report badge. `1 жалоба / 2 жалобы / 5 жалоб`. */
function reportLabel(n: number): string {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod10 === 1 && mod100 !== 11) return `${String(n)} жалоба`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) return `${String(n)} жалобы`;
  return `${String(n)} жалоб`;
}

/**
 * Who wrote it.
 *
 * A guest and a customer must not be mistakable at a glance, so they differ in
 * three ways at once: the guest is prefixed with a label, is not a link, and is
 * set in muted mono so the address reads as data rather than as a name. A
 * guest's email is never a link — there is nowhere to go, and a dead link is
 * worse than none.
 */
function Author({ review }: { review: AdminReview }) {
  if (review.user_id && review.user_name) {
    return (
      <Link
        to={`/customers/${review.user_id}`}
        className="font-medium text-[var(--text-primary)] underline-offset-2 hover:underline"
      >
        {review.user_name}
      </Link>
    );
  }
  if (review.guest_email) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <Badge tone="bg-[var(--bg-muted)] text-[var(--text-secondary)]">Гость</Badge>
        <span className="font-mono text-[var(--text-secondary)]">{review.guest_email}</span>
      </span>
    );
  }
  return <span className="text-[var(--text-secondary)]">—</span>;
}

export interface ReviewRowProps {
  review: AdminReview;
  showBrand?: boolean;
  /** Focus this brand in the by-brand block. Omitted inside a brand's own list. */
  onPickBrand?: (slug: string) => void;
  onModerate: (action: "hide" | "unhide" | "remove") => void;
  /** True only while THIS row is being moderated — a page-wide pending flag
   *  disables every button on screen and makes the panel feel broken. */
  busy: boolean;
}

export function ReviewRow({
  review: r,
  showBrand = true,
  onPickBrand,
  onModerate,
  busy,
}: ReviewRowProps) {
  const flagged = r.report_count > 0;
  const brandLabel = r.brand_name ?? r.brand_slug ?? "бренд удалён";

  return (
    <li
      className={`grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 px-4 py-3 sm:grid-cols-[auto_1fr_auto] ${
        // Read at scroll speed, before any text: a reported row is marked on
        // its edge and tinted, so it cannot be skimmed past.
        flagged ? "shadow-[inset_3px_0_0_0_var(--danger)]" : ""
      }`}
      style={
        flagged
          ? { background: "color-mix(in oklab, var(--danger) 7%, var(--bg-surface))" }
          : undefined
      }
    >
      {showBrand ? (
        <button
          type="button"
          onClick={() => {
            if (r.brand_slug) onPickBrand?.(r.brand_slug);
          }}
          title={`Все отзывы: ${brandLabel}`}
          className="mt-0.5 shrink-0 rounded-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent)]"
        >
          <Thumb src={r.brand_logo_url} name={brandLabel} size={32} />
        </button>
      ) : (
        <span className="mt-0.5 shrink-0">
          <Stars rating={r.rating} />
        </span>
      )}

      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          {showBrand && <Stars rating={r.rating} />}
          {showBrand && (
            <button
              type="button"
              onClick={() => {
                if (r.brand_slug) onPickBrand?.(r.brand_slug);
              }}
              className="text-sm font-medium hover:underline"
            >
              {brandLabel}
            </button>
          )}
          {/* Only when it is not the normal case: a chip on every published row
              is noise that buries the two statuses worth seeing. */}
          {r.status !== "published" && <StatusChip domain="reviewStatus" value={r.status} />}
          {flagged && (
            <Badge tone="bg-[var(--danger-soft)] text-[var(--danger-fg)]">
              <Flag className="size-3" aria-hidden />
              {reportLabel(r.report_count)}
            </Badge>
          )}
        </div>

        {r.body ? (
          <p className="mt-1.5 whitespace-pre-line text-sm text-[var(--text-primary)]">{r.body}</p>
        ) : (
          /* Not "—": the operator needs to know there is nothing to moderate,
             which is a different fact from a missing value. */
          <p className="mt-1.5 text-sm italic text-[var(--text-secondary)]">
            Без текста — только оценка
          </p>
        )}

        <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--text-secondary)]">
          <Author review={r} />
          <span aria-hidden>·</span>
          <CopyId value={r.order_id} to={`/orders/${r.order_id}`} />
          <span aria-hidden>·</span>
          <time dateTime={r.created_at}>
            {new Date(r.created_at).toLocaleString("ru", {
              day: "2-digit",
              month: "2-digit",
              year: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </time>
        </div>
      </div>

      {/* Always visible, never hover-revealed: the queue is scanned with the
          eyes and acted on with the mouse, and hidden controls make an operator
          hunt for what they came to do. */}
      <div className="col-span-2 flex items-start justify-end gap-3 text-xs sm:col-span-1">
        {r.status === "published" ? (
          <button
            type="button"
            className="text-[var(--warning-fg)] hover:underline disabled:opacity-50"
            onClick={() => {
              onModerate("hide");
            }}
            disabled={busy}
          >
            Скрыть
          </button>
        ) : (
          <button
            type="button"
            className="text-[var(--success-fg)] hover:underline disabled:opacity-50"
            onClick={() => {
              onModerate("unhide");
            }}
            disabled={busy}
          >
            Вернуть
          </button>
        )}
        {r.status !== "removed" && (
          <button
            type="button"
            className="text-[var(--danger)] hover:underline disabled:opacity-50"
            onClick={() => {
              onModerate("remove");
            }}
            disabled={busy}
          >
            Удалить
          </button>
        )}
      </div>
    </li>
  );
}
