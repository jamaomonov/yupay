import { Check, Copy } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { writeToClipboard } from "@/lib/clipboard";

/**
 * A full value, shown whole, with a button that copies it.
 *
 * `CopyId` truncates to eight characters, which is right for a UUID in a
 * table and wrong for the two things this feature shows: a key id an
 * operator pastes into a merchant's config, and a secret that exists for
 * exactly one page view. Both must be readable in full and copyable without
 * a hand-made selection — dragging across 43 monospace characters on a
 * laptop trackpad is how a trailing space gets into somebody's `.env`.
 */
export function CopyValue({
  value,
  label,
  done,
  size = "sm",
}: {
  value: string;
  label: string;
  done: string;
  /** `xs` for the key id in a list row, `sm` for a panel. */
  size?: "xs" | "sm";
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  return (
    <div className="flex items-start gap-2">
      <code
        className={`min-w-0 flex-1 break-all font-mono ${size === "xs" ? "text-xs" : "text-sm"}`}
      >
        {value}
      </code>
      <button
        type="button"
        aria-label={copied ? done : label}
        // The label flips on a timer, and a page translator that has replaced
        // this text node leaves React unable to update it — the failure that
        // took the merchant cabinet to its error boundary on 2026-09-21.
        translate="no"
        onClick={() => {
          void writeToClipboard(value).then((ok) => {
            if (!ok) return;
            setCopied(true);
            if (timer.current) clearTimeout(timer.current);
            timer.current = setTimeout(() => {
              setCopied(false);
            }, 1400);
          });
        }}
        className="rounded-btn shrink-0 border px-2.5 py-1 text-xs text-[var(--text-secondary)]"
      >
        <span className="inline-flex items-center gap-1.5">
          {copied ? <Check size={13} /> : <Copy size={13} />}
          {copied ? done : label}
        </span>
      </button>
    </div>
  );
}
