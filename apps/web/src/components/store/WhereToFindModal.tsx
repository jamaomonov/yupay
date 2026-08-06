"use client";

import { X } from "lucide-react";
import { useEffect, useRef } from "react";

/**
 * Modal that explains where to find the account identifier (player ID /
 * Steam login). The body is plain text today, but the "где найти" hint opens
 * a dialog rather than expanding inline precisely because this is the
 * container future rich help — profile screenshots, numbered step images —
 * will render into without another layout change.
 *
 * Mirrors the app's modal convention (see LoginModal): a full-screen dialog
 * layer, a backdrop that closes on click, Escape to dismiss, and focus that
 * moves into the card on open and back to the opener on close.
 */
export function WhereToFindModal({
  open,
  title,
  body,
  closeLabel,
  onClose,
}: {
  open: boolean;
  title: string;
  body: string;
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

        {/* Plain-text help today (newlines preserved). Screenshots and step
            images will slot in here once the catalog carries them. */}
        <div className="text-tx-mute mt-4 whitespace-pre-line text-[14px] leading-relaxed">
          {body}
        </div>
      </div>
    </div>
  );
}
