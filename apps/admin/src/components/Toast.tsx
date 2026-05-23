/**
 * Toast notifications — small, single source of truth.
 *
 * Why a custom store instead of pulling in react-hot-toast / sonner: the
 * surface area we need is tiny (success / error / info, dismiss timer,
 * one stacked region), and a 60-line Zustand store avoids dragging another
 * library into the admin bundle.
 *
 * Architecture:
 *   - `useToast()` exposes `success` / `error` / `info` / `dismiss`.
 *   - `<ToastRegion />` renders the live region — drop it once near the
 *     root of the app shell (Layout). It listens to the store.
 *   - Each toast auto-dismisses after `duration` ms (default 4 s); error
 *     toasts stay until clicked because operators tend to actually want
 *     to read them.
 */

import { useEffect } from "react";
import { create } from "zustand";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

export type ToastTone = "success" | "error" | "info";

interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
  /** Optional ms-duration override. `null` = sticky (manual dismiss only). */
  duration: number | null;
}

interface ToastState {
  items: Toast[];
  push: (toast: Omit<Toast, "id">) => number;
  dismiss: (id: number) => void;
}

let nextId = 1;

const useToastStore = create<ToastState>((set) => ({
  items: [],
  push: (toast) => {
    const id = nextId++;
    set((s) => ({ items: [...s.items, { ...toast, id }] }));
    return id;
  },
  dismiss: (id) => {
    set((s) => ({ items: s.items.filter((t) => t.id !== id) }));
  },
}));

const DEFAULT_DURATIONS: Record<ToastTone, number | null> = {
  success: 4_000,
  info: 4_000,
  error: null, // sticky — errors deserve a deliberate dismiss.
};

export function useToast() {
  const push = useToastStore((s) => s.push);
  const dismiss = useToastStore((s) => s.dismiss);
  return {
    success: (message: string, duration?: number) =>
      push({ tone: "success", message, duration: duration ?? DEFAULT_DURATIONS.success }),
    error: (message: string, duration?: number | null) =>
      push({ tone: "error", message, duration: duration ?? DEFAULT_DURATIONS.error }),
    info: (message: string, duration?: number) =>
      push({ tone: "info", message, duration: duration ?? DEFAULT_DURATIONS.info }),
    dismiss,
  };
}

const ICONS: Record<ToastTone, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: AlertTriangle,
  info: Info,
};

const SURFACES: Record<ToastTone, string> = {
  success: "border-[var(--success-fg)]/40 bg-[var(--success-soft)] text-[var(--success-fg)]",
  error: "border-[var(--danger-fg)]/40 bg-[var(--danger-soft)] text-[var(--danger-fg)]",
  info: "border-[var(--info-fg)]/40 bg-[var(--info-soft)] text-[var(--info-fg)]",
};

export function ToastRegion() {
  const items = useToastStore((s) => s.items);
  const dismiss = useToastStore((s) => s.dismiss);
  return (
    <div
      aria-live="polite"
      aria-atomic="false"
      className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-full max-w-sm flex-col gap-2"
    >
      {items.map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={() => { dismiss(t.id); }} />
      ))}
    </div>
  );
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const Icon = ICONS[toast.tone];
  useEffect(() => {
    if (toast.duration === null) return;
    const t = window.setTimeout(onDismiss, toast.duration);
    return () => { window.clearTimeout(t); };
  }, [toast.duration, onDismiss]);
  return (
    <div
      role={toast.tone === "error" ? "alert" : "status"}
      className={[
        "pointer-events-auto flex items-start gap-3 rounded-lg border px-4 py-3 text-sm shadow-[var(--shadow-md)]",
        SURFACES[toast.tone],
      ].join(" ")}
    >
      <Icon className="mt-0.5 size-4 flex-shrink-0" aria-hidden />
      <p className="min-w-0 flex-1 break-words">{toast.message}</p>
      <button
        type="button"
        onClick={onDismiss}
        aria-label="Закрыть уведомление"
        className="-mr-1 grid size-6 flex-shrink-0 place-items-center rounded text-current opacity-60 hover:opacity-100 hover:bg-black/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-current focus-visible:ring-offset-2 focus-visible:ring-offset-transparent"
      >
        <X className="size-3.5" aria-hidden />
      </button>
    </div>
  );
}
