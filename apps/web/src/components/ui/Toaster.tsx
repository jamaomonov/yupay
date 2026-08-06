"use client";

import { Check, Info, X, type LucideIcon } from "lucide-react";

import { useToast, type ToastTone } from "@/store/useToast";

/** Tone → tile styling. Mirrors `StatusBlock`'s palette so feedback across the
 *  storefront reads as one system (`#FF6B6B` is the existing error rose — the
 *  brand palette has no dedicated red token). */
const TONE: Record<ToastTone, { ring: string; icon: string; Icon: LucideIcon }> = {
  success: { ring: "ring-primary/30", icon: "text-primary", Icon: Check },
  error: { ring: "ring-[#FF6B6B]/30", icon: "text-[#FF6B6B]", Icon: X },
  info: { ring: "ring-border-2", icon: "text-tx-mute", Icon: Info },
};

/**
 * Global toast viewport, mounted once in `Providers`.
 *
 * Sits above the mobile sticky pay bar (`z-40`, `bottom-0`) and clears the
 * desktop support FAB (`bottom-6 right-6`), so feedback never lands underneath
 * either. `pointer-events-none` on the stack keeps the page clickable; only the
 * toasts themselves capture clicks (tap to dismiss).
 *
 * The container is an `aria-live` region so screen readers announce a toast
 * without moving focus — a copy confirmation must not steal it mid-flow.
 */
export function Toaster() {
  const toasts = useToast((s) => s.toasts);
  const dismiss = useToast((s) => s.dismiss);

  return (
    <div
      role="status"
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed inset-x-0 bottom-24 z-[110] flex flex-col items-center gap-2 px-4 lg:inset-x-auto lg:right-6 lg:items-end"
    >
      {toasts.map((t) => {
        const { ring, icon, Icon } = TONE[t.tone];
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => {
              dismiss(t.id);
            }}
            className={`anim-sheet-in border-border bg-card/95 text-foreground pointer-events-auto flex max-w-[min(28rem,100%)] items-center gap-2.5 rounded-xl border px-4 py-3 text-left text-sm shadow-[0_12px_30px_-10px_rgba(0,0,0,0.6)] ring-1 ring-inset backdrop-blur-xl ${ring}`}
          >
            <Icon size={16} className={`shrink-0 ${icon}`} aria-hidden="true" />
            <span className="min-w-0">{t.message}</span>
          </button>
        );
      })}
    </div>
  );
}
