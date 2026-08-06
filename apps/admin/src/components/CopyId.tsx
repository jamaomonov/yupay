/**
 * A truncated identifier that can be copied.
 *
 * The admin shows UUIDs everywhere and truncates all of them to eight
 * characters, which is enough to recognise a row and useless for anything
 * else: pasting an id into a ticket, a psql query, or a provider's console
 * meant re-typing it from the detail page. Every id chip is now a copy button,
 * and the full value is always in the tooltip.
 */

import { Check, Copy } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

interface CopyIdProps {
  /** The full identifier. Never truncate before passing it in. */
  value: string;
  /** How much of the id to show. Eight characters is the admin-wide default. */
  chars?: number;
  /** Rendered before the id, e.g. "user" or "order". */
  label?: string;
  className?: string;
}

/** Milliseconds the confirmation tick stays up after a copy. */
const FEEDBACK_MS = 1400;

async function writeToClipboard(text: string): Promise<boolean> {
  // `navigator.clipboard` is undefined outside a secure context, which is how
  // the admin gets served when someone opens it over plain http on an internal
  // address. Fall back rather than throw — the id is still in the tooltip
  // either way, but the button should not look broken.
  // The cast widens rather than narrows: lib.dom declares `navigator.clipboard`
  // as always present, which is false outside a secure context.
  const clipboard = navigator.clipboard as Clipboard | undefined;
  if (clipboard) {
    try {
      await clipboard.writeText(text);
      return true;
    } catch {
      // Permission denied or the document lost focus; try the fallback.
    }
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try {
    // Deprecated, and the only copy path left when the async API is missing.
    // eslint-disable-next-line @typescript-eslint/no-deprecated
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.body.removeChild(area);
  }
}

export function CopyId({ value, chars = 8, label, className = "" }: CopyIdProps) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const copy = useCallback(
    (event: React.MouseEvent) => {
      // These chips live inside clickable table rows; copying an id must not
      // also navigate away from the list the operator is working through.
      event.stopPropagation();
      event.preventDefault();
      void writeToClipboard(value).then((ok) => {
        setState(ok ? "copied" : "failed");
        if (timerRef.current) clearTimeout(timerRef.current);
        timerRef.current = setTimeout(() => {
          setState("idle");
        }, FEEDBACK_MS);
      });
    },
    [value],
  );

  const shown = value.length > chars ? `${value.slice(0, chars)}…` : value;
  const title =
    state === "failed"
      ? `${value} — скопировать не удалось, выдели вручную`
      : `${value} — скопировать`;

  return (
    <button
      type="button"
      onClick={copy}
      title={title}
      aria-label={`Скопировать ${label ? `${label} ` : ""}${value}`}
      className={`group inline-flex max-w-full items-center gap-1 font-mono text-inherit underline-offset-2 hover:underline ${className}`}
    >
      {label && <span className="text-[var(--text-secondary)]">{label}</span>}
      <span className="truncate">{shown}</span>
      {state === "copied" ? (
        <Check className="size-3 flex-shrink-0 text-[var(--success,var(--accent))]" aria-hidden />
      ) : (
        <Copy
          className="size-3 flex-shrink-0 opacity-0 transition-opacity group-hover:opacity-60 group-focus-visible:opacity-60"
          aria-hidden
        />
      )}
      {state === "copied" && <span className="sr-only">Скопировано</span>}
      {state === "failed" && <span className="sr-only">Скопировать не удалось</span>}
    </button>
  );
}
