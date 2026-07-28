import { create } from "zustand";

interface OrderDeliveredModalState {
  /** The order to show in the modal, or `null` when closed. */
  orderId: string | null;
  open: (orderId: string) => void;
  close: () => void;
}

/**
 * Global "order delivered" modal state, opened by `useOrderSocket` on an
 * `order.delivered` WS message. The modal UI itself is built on top of this
 * store in a follow-up task; this task only owns the open/close state.
 */
export const useOrderDeliveredModal = create<OrderDeliveredModalState>((set) => ({
  orderId: null,
  open: (orderId) => {
    set({ orderId });
  },
  close: () => {
    set({ orderId: null });
  },
}));
