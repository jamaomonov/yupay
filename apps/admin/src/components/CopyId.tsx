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
import { Link } from "react-router-dom";

import { writeToClipboard } from "@/lib/clipboard";

interface CopyIdProps {
  /** The full identifier. Never truncate before passing it in. */
  value: string;
  /** How much of the id to show. Eight characters is the admin-wide default. */
  chars?: number;
  /** Rendered before the id, e.g. "user" or "order". */
  label?: string;
  /**
   * Where this id lives. When given, the id itself becomes a link and copying
   * moves to a button beside it — an id that names a row somewhere else should
   * take you there, and a button nested inside a link is invalid HTML anyway.
   */
  to?: string;
  className?: string;
}

/** Milliseconds the confirmation tick stays up after a copy. */
const FEEDBACK_MS = 1400;

export function CopyId({ value, chars = 8, label, to, className = "" }: CopyIdProps) {
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

  const feedback = (
    <>
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
    </>
  );

  if (to) {
    return (
      <span className={`group inline-flex max-w-full items-center gap-1 font-mono ${className}`}>
        {label && <span className="text-[var(--text-secondary)]">{label}</span>}
        <Link
          to={to}
          title={value}
          onClick={(event) => {
            // The row underneath is clickable too; without this, following the
            // link would also fire the row's own navigation.
            event.stopPropagation();
          }}
          className="truncate underline-offset-2 hover:underline"
        >
          {shown}
        </Link>
        <button
          type="button"
          onClick={copy}
          title={title}
          aria-label={`Скопировать ${label ? `${label} ` : ""}${value}`}
          className="inline-flex flex-shrink-0 items-center"
        >
          {feedback}
        </button>
      </span>
    );
  }

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
      {feedback}
    </button>
  );
}
