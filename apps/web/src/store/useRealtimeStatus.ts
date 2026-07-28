import { create } from "zustand";

interface RealtimeStatusState {
  connected: boolean;
  setConnected: (connected: boolean) => void;
}

/** Tracks whether the order-updates WebSocket is currently open. Gates REST polling. */
export const useRealtimeStatus = create<RealtimeStatusState>((set) => ({
  connected: false,
  setConnected: (connected) => {
    set({ connected });
  },
}));
