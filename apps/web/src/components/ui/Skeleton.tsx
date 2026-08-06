/**
 * Loading placeholder block.
 *
 * A skeleton that mirrors the shape of the content it stands in for reads as
 * "almost there" — a bare "Loading…" line reads as "nothing is happening", and
 * it also shifts the layout the moment real content lands. `animate-pulse` is
 * stilled globally under `prefers-reduced-motion` (see globals.css).
 *
 * Always `aria-hidden`: the surrounding region carries the live/busy semantics,
 * so a screen reader announces "loading" once instead of reading empty boxes.
 */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <span className={`bg-muted block animate-pulse rounded ${className}`} aria-hidden="true" />
  );
}
