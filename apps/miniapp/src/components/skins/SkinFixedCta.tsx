import { createPortal } from "react-dom";

import type { ReactNode } from "react";

/**
 * The skin page's bottom action bar, above the nav. Portalled to <body>: the page
 * wrapper animates with a transform, and a transformed ancestor would make "fixed"
 * mean fixed to the page, not the screen. A solid button on a fade of the background,
 * never a see-through one over the content.
 */
export function SkinFixedCta({
  label,
  onPress,
  disabled = false,
  muted = false,
}: {
  label: ReactNode;
  onPress: () => void;
  /** Nothing to do (a request in flight, or a step that cannot be taken yet). */
  disabled?: boolean;
  /** Looks inactive but still answers a tap — e.g. to take the buyer to what is missing. */
  muted?: boolean;
}) {
  return createPortal(
    <div
      className="fixed bottom-[calc(var(--app-nav-total)_+_8px)] left-1/2 z-40 w-full max-w-[430px] -translate-x-1/2 px-4 pb-2 pt-6"
      style={{ background: "linear-gradient(to top, hsl(var(--background)) 60%, transparent)" }}
    >
      <button
        type="button"
        aria-disabled={muted || undefined}
        disabled={disabled}
        onClick={onPress}
        className="bg-primary flex w-full items-center justify-center gap-2 rounded-2xl py-4 text-base font-bold tracking-wide text-black transition-all disabled:cursor-not-allowed disabled:bg-[hsl(var(--surface-2))] disabled:text-white/55 aria-disabled:bg-[hsl(var(--surface-2))] aria-disabled:text-white/55"
      >
        {label}
      </button>
    </div>,
    document.body,
  );
}
