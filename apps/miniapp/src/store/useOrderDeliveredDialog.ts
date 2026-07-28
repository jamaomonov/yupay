import { create } from "zustand";

interface OrderDeliveredDialogState {
  /** The order to show in the dialog, or `null` when closed. */
  orderId: string | null;
  open: (orderId: string) => void;
  close: () => void;
}

/**
 * Global "order delivered" dialog state, opened by `useOrderSocket` on an
 * `order.delivered` WS message. `OrderDeliveredDialog` renders the UI on top
 * of this store; this module only owns the open/close state.
 */
export const useOrderDeliveredDialog = create<OrderDeliveredDialogState>((set) => ({
  orderId: null,
  open: (orderId) => {
    set({ orderId });
  },
  close: () => {
    set({ orderId: null });
  },
}));
