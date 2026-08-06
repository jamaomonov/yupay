import { create } from "zustand";

/** Visual/semantic flavour of a toast. */
export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: string;
  message: string;
  tone: ToastTone;
}

interface ToastState {
  toasts: Toast[];
  /** Show a toast; it auto-dismisses after {@link AUTO_DISMISS_MS}. */
  push: (message: string, tone?: ToastTone) => void;
  dismiss: (id: string) => void;
}

/** How long a toast stays on screen. Long enough to read a short sentence,
 *  short enough not to sit over the content the user is trying to reach. */
const AUTO_DISMISS_MS = 4_000;
/** Cap the stack so a burst (e.g. copy spam) can't cover the viewport. */
const MAX_TOASTS = 3;

let seq = 0;

/**
 * Global toast queue for the storefront.
 *
 * Deliberately a tiny zustand store rather than a Radix/Sonner dependency: the
 * web bundle has a per-route budget (see AGENTS.md §10) and the app already
 * standardises on zustand for global UI state (`useLoginModal`). The rendering
 * half lives in `components/ui/Toaster.tsx`, mounted once in `Providers`.
 */
export const useToast = create<ToastState>((set, get) => ({
  toasts: [],
  push: (message, tone = "info") => {
    seq += 1;
    const id = `t${String(seq)}`;
    set((s) => ({ toasts: [...s.toasts, { id, message, tone }].slice(-MAX_TOASTS) }));
    // Self-expiring: the viewport is render-only, so nothing else would clear it.
    setTimeout(() => {
      get().dismiss(id);
    }, AUTO_DISMISS_MS);
  },
  dismiss: (id) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));

/** Imperative helper for non-component callers (event handlers, mutations). */
export const toast = {
  success: (message: string) => {
    useToast.getState().push(message, "success");
  },
  error: (message: string) => {
    useToast.getState().push(message, "error");
  },
  info: (message: string) => {
    useToast.getState().push(message, "info");
  },
};
