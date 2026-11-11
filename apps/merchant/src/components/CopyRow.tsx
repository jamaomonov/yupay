"use client";

import { Check, Copy } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

const DONE_MS = 1500;

interface CopyRowProps {
  /** What lands on the clipboard — may differ from what is shown. */
  value: string;
  /** What the row shows; tapping it copies too. */
  children: ReactNode;
  /** Both labels come from the caller's namespace. */
  label: string;
  done: string;
  /** Classes for the shown value (size, font, colour). */
  className?: string;
}

/**
 * A value on the left, a square copy button on the right. Tapping either
 * copies; the icon turns into a tick and «Скопировано» shows for a moment.
 */
export function CopyRow({ value, children, label, done, className }: CopyRowProps) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const copy = () => {
    // `writeText` rejects without a user gesture or on an insecure origin.
    // Silently: the value is on screen and can still be selected.
    void navigator.clipboard.writeText(value).then(
      () => {
        setCopied(true);
        if (timer.current !== null) clearTimeout(timer.current);
        timer.current = setTimeout(() => {
          setCopied(false);
        }, DONE_MS);
      },
      () => undefined,
    );
  };

  return (
    <div className="mt-1 flex items-center gap-3">
      <button
        type="button"
        onClick={copy}
        title={label}
        className={`min-w-0 flex-1 cursor-copy text-left ${className ?? ""}`}
      >
        {children}
      </button>
      <span className="relative shrink-0">
        <button
          type="button"
          onClick={copy}
          aria-label={label}
          title={label}
          className="border-border bg-card-2 rounded-btn pointer-fine:hover:border-primary text-tx-mute flex h-10 w-10 items-center justify-center border transition-colors"
        >
          {copied ? (
            <Check aria-hidden size={18} className="text-primary-ink" />
          ) : (
            <Copy aria-hidden size={18} />
          )}
        </button>
        {/* `translate="no"`: a page translator replacing this text node leaves
            React a node it cannot remove (see CopyButton). */}
        <span
          role="status"
          translate="no"
          className={`bg-foreground text-bg pointer-events-none absolute bottom-full right-0 mb-1.5 whitespace-nowrap rounded-md px-2 py-1 text-xs font-semibold transition-opacity ${copied ? "opacity-100" : "opacity-0"}`}
        >
          {copied ? done : ""}
        </span>
      </span>
    </div>
  );
}
