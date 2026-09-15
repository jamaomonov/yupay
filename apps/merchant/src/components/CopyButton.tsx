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
