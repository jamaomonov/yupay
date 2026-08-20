"use client";

import { useEffect, useId, useRef, useState } from "react";

import { buttonStyles } from "@/lib/button";

/**
 * Last look before an irreversible payment.
 *
 * Pressing "Оплатить" used to hand the buyer straight to the acquirer: no
 * summary, no chance to re-read the game ID they typed a minute earlier. A
 * mistyped ID is the most expensive error in this category — the top-up lands
 * on a stranger's account and the refund policy says so plainly ("если ID
 * указан неверно по вашей вине"). So the one thing that cannot be undone gets
 * one confirmation.
 *
 * Where the catalogue has no player check at all (Genshin, Honkai Star Rail —
 * the supplier reports "no validation required"), the dialog additionally asks
 * the buyer to confirm they checked the ID in-game. That is the only place in
 * the flow where anyone can catch the typo.
 *
 * Mirrors the app's modal convention (see WhereToFindModal): backdrop click,
 * Escape, focus moved into the card and restored to the opener.
 */
export interface ConfirmPurchaseRow {
  label: string;
  value: string;
}

export function ConfirmPurchaseModal({
  open,
  title,
  rows,
  totalLabel,
  totalValue,
  warning,
  attestation,
  confirmLabel,
  cancelLabel,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  rows: ConfirmPurchaseRow[];
  totalLabel: string;
  totalValue: string;
  warning: string;
  /** Required tick-box copy; omitted when the ID was verified upstream. */
  attestation?: string | undefined;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const cardRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);
  const [attested, setAttested] = useState(false);
  const attestId = useId();

  useEffect(() => {
    if (open) {
      openerRef.current = document.activeElement as HTMLElement | null;
      cardRef.current?.focus();
      // Each opening starts unticked: the buyer may have come back to edit the
      // id, and a tick carried over from last time would attest to nothing.
      setAttested(false);
    } else {
      openerRef.current?.focus();
      openerRef.current = null;
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [open, onClose]);

  if (!open) return null;

  const blocked = Boolean(attestation) && !attested;

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
        className="border-border bg-card relative z-10 max-h-[85vh] w-full max-w-[440px] overflow-y-auto rounded-2xl border p-6 shadow-2xl outline-none"
      >
        <h2 className="font-display text-xl font-bold leading-tight tracking-[-0.02em]">{title}</h2>

        <dl className="border-border/70 mt-5 divide-y divide-[hsl(var(--border)/0.7)] border-y">
          {rows.map((row) => (
            <div key={row.label} className="flex items-start justify-between gap-4 py-2.5">
              <dt className="text-tx-mute text-[13px]">{row.label}</dt>
              <dd className="min-w-0 break-words text-right text-[14px] font-semibold">
                {row.value}
              </dd>
            </div>
          ))}
          <div className="flex items-baseline justify-between gap-4 py-3">
            <dt className="text-tx-mute text-[13px]">{totalLabel}</dt>
            <dd className="font-display text-lg font-extrabold">{totalValue}</dd>
          </div>
        </dl>

        <p className="text-tx-mute mt-4 text-[13px] leading-relaxed">{warning}</p>

        {attestation && (
          <label
            htmlFor={attestId}
            className="border-border bg-muted/40 mt-4 flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 text-[13px] leading-snug"
          >
            <input
              id={attestId}
              type="checkbox"
              checked={attested}
              onChange={(e) => {
                setAttested(e.target.checked);
              }}
              className="accent-primary mt-0.5 h-4 w-4 shrink-0"
            />
            <span>{attestation}</span>
          </label>
        )}

        <div className="mt-5 flex flex-col-reverse gap-2.5 sm:flex-row">
          <button
            type="button"
            onClick={onClose}
            className={buttonStyles({ variant: "ghost", size: "md", className: "flex-1" })}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={blocked}
            className={buttonStyles({ size: "md", className: "flex-1" })}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
