import { Loader2 } from "lucide-react";

/**
 * A spinner and what is loading. Grey placeholders alone read as "the page is laid out";
 * on a list that takes a few seconds the reseller also needs to see it is on its way.
 */
export function LoadingNote({ text, className = "" }: { text: string; className?: string }) {
  return (
    <p
      role="status"
      aria-live="polite"
      className={`text-tx-mute flex items-center gap-2 text-sm ${className}`}
    >
      <Loader2 aria-hidden size={16} className="text-primary-ink animate-spin" />
      {text}
    </p>
  );
}
