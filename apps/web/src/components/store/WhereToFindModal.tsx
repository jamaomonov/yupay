"use client";

import { X } from "lucide-react";
import Image from "next/image";
import { useEffect, useRef } from "react";

import { isOptimizable } from "@/lib/image";

/**
 * One step image for the "где найти" walkthrough, already localized by the
 * caller (same contract as `body` below — this component stays presentation
 * -only and never needs a locale or translator of its own).
 */
export interface WhereToFindImage {
  url: string;
  /** Meaningful, never-empty alt text (WCAG 1.1.1): the caption when the
   *  field has one, otherwise a "Step N of M" fallback computed by the
   *  caller. */
  alt: string;
  /** The same caption, shown as visible text under the image when present. */
  caption: string | null;
}

/**
 * Modal that explains where to find the account identifier (player ID /
 * Steam login). The body is plain text; when the field also carries step
 * images (profile screenshots, the id circled) they render below it, in
 * order, each with its caption — this is the container the docstring here
 * used to promise them into, now filled in.
 *
 * Mirrors the app's modal convention (see LoginModal): a full-screen dialog
 * layer, a backdrop that closes on click, Escape to dismiss, and focus that
 * moves into the card on open and back to the opener on close. The card
 * itself is capped to 85vh and scrolls internally, so a tall stack of
 * screenshots never pushes the close button off-screen.
 */
export function WhereToFindModal({
  open,
  title,
  body,
  images,
  closeLabel,
  onClose,
}: {
  open: boolean;
  title: string;
  body: string;
  /** Ordered walkthrough images, or `null`/absent/empty when the field has
   *  none — a field may have text, images, or both; never assume this list
   *  is non-empty. */
  images?: WhereToFindImage[] | null;
  closeLabel: string;
  onClose: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  // Focus into the dialog on open; restore it to the opener on close
  // (WCAG 2.4.3 focus order).
  useEffect(() => {
    if (open) {
      openerRef.current = document.activeElement as HTMLElement | null;
      cardRef.current?.focus();
    } else {
      openerRef.current?.focus();
      openerRef.current = null;
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      // Keep Tab inside the dialog. It is `aria-modal`, so assistive tech is
      // already told the rest of the page is inert — without a trap the focus
      // ring wanders off behind the backdrop and the promise is false.
      if (e.key !== "Tab") return;
      const card = cardRef.current;
      if (!card) return;
      const focusable = card.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, select, textarea, [tabindex]:not([tabindex="-1"])',
      );
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  const stepImages = images ?? [];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
    >
      <button
        type="button"
        aria-hidden="true"
        tabIndex={-1}
        onClick={onClose}
        className="bg-bg/80 absolute inset-0 backdrop-blur-sm"
      />
      <div
        ref={cardRef}
        tabIndex={-1}
        className="border-border bg-card relative z-10 max-h-[85vh] w-full max-w-[460px] overflow-y-auto rounded-2xl border p-7 shadow-2xl outline-none"
      >
        <button
          type="button"
          onClick={onClose}
          aria-label={closeLabel}
          className="text-tx-mute hover:bg-muted hover:text-foreground absolute right-3 top-3 flex h-10 w-10 items-center justify-center rounded-full transition"
        >
          <X size={18} />
        </button>

        <h2 className="font-display pr-10 text-xl font-bold leading-tight tracking-[-0.02em]">
          {title}
        </h2>

        {/* Plain-text help (newlines preserved). The text always stays: a
            customer on a slow connection or with images blocked still needs
            this. */}
        {body && (
          <div className="text-tx-mute mt-4 whitespace-pre-line text-[14px] leading-relaxed">
            {body}
          </div>
        )}

        {stepImages.length > 0 && (
          <ol className="mt-5 flex flex-col gap-4">
            {stepImages.map((img, i) => (
              <li key={img.url} className="flex flex-col gap-2">
                <div className="flex items-center gap-2">
                  <span className="bg-primary/15 text-primary flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold">
                    {i + 1}
                  </span>
                  {img.caption && (
                    <span className="text-tx-mute text-[13px] font-medium">{img.caption}</span>
                  )}
                </div>
                {/* Portrait box: a phone screenshot's own shape. `object-contain`
                    letterboxes rather than crops, so the circled id near the
                    edge of the source screenshot is never cut off. */}
                <div className="border-border bg-card-2 relative aspect-[3/4] w-full overflow-hidden rounded-xl border">
                  <Image
                    src={img.url}
                    alt={img.alt}
                    fill
                    unoptimized={!isOptimizable(img.url)}
                    sizes="(min-width: 460px) 412px, 100vw"
                    className="object-contain"
                  />
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}
