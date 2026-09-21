"use client";

import { Check, Copy } from "lucide-react";
import { useState } from "react";

interface CopyButtonProps {
  value: string;
  /** Both labels come from the caller's namespace — this button has none. */
  label: string;
  done: string;
}

/**
 * Copies one value and says so for two seconds.
 *
 * The things worth copying in this cabinet — an API secret, a voucher code, an
 * order id — are exactly the things that are painful to retype and easy to
 * mis-select by hand.
 */
export function CopyButton({ value, label, done }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);

  return (
    <button
      type="button"
      // The label swaps to «Скопировано» and back on a two-second timer, and
      // a text node a page translator has replaced is a node React can no
      // longer remove — `NotFoundError: Failed to execute 'removeChild'`,
      // which takes the whole cabinet to its error boundary. Reported from a
      // merchant reading the Russian cabinet through Chrome's translator on
      // 2026-09-21. `translate="no"` on the elements React rewrites, not on
      // the app: the rest of the page still translates.
      translate="no"
      aria-label={copied ? done : label}
      onClick={() => {
        // `writeText` rejects without a user gesture or on an insecure origin.
        // Silently: the value is on screen and can still be selected.
        void navigator.clipboard.writeText(value).then(
          () => {
            setCopied(true);
            setTimeout(() => {
              setCopied(false);
            }, 2000);
          },
          () => undefined,
        );
      }}
      className="border-border rounded-btn text-tx-mute inline-flex items-center gap-1.5 border px-2.5 py-1.5 text-xs"
    >
      {copied ? <Check size={13} /> : <Copy size={13} />}
      {copied ? done : label}
    </button>
  );
}
