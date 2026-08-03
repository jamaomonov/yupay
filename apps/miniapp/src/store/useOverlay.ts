import { create } from "zustand";

interface OverlayState {
  /** Number of full-screen overlays (sheets/modals) currently mounted. */
  count: number;
  open: () => void;
  close: () => void;
}

/**
 * Counts open full-screen overlays so chrome that would otherwise paint on top
 * of them — notably the fixed {@link BottomNav}, which shares their `z-50` and
 * is later in the DOM — can hide while any overlay is up. A counter (not a
 * boolean) keeps it correct if two overlays ever stack: the nav reappears only
 * once the last one closes.
 */
export const useOverlay = create<OverlayState>((set) => ({
  count: 0,
  open: () => {
    set((s) => ({ count: s.count + 1 }));
  },
  close: () => {
    set((s) => ({ count: Math.max(0, s.count - 1) }));
  },
}));

/** True while at least one full-screen overlay is mounted. */
export const useOverlayOpen = (): boolean => useOverlay((s) => s.count > 0);
