/**
 * Factory for the order-updates WebSocket used by `useOrderSocket`.
 *
 * The URL is derived from the same `VITE_API_BASE_URL` the REST client
 * (`./api`) uses, swapping the scheme for `ws`/`wss`. Auth is a short-lived
 * handshake token minted by `POST /api/v1/realtime/handshake`; `OrderSocket`
 * re-invokes `getToken` on every reconnect, so a stale/expired token never
 * wedges the connection.
 */
import { OrderSocket, type OrderUpdateMessage } from "@yupay/api-client";

import { apiBase, apiPost } from "./api";

const WS_URL = `${apiBase.replace(/^http/, "ws")}/api/v1/realtime/ws/orders`;

export interface OrderSocketHandlers {
  onMessage: (message: OrderUpdateMessage) => void;
  onOpen?: () => void;
  onClose?: () => void;
}

/** Creates (but does not connect) an `OrderSocket` wired to the app's REST client. */
export function createOrderSocket(handlers: OrderSocketHandlers): OrderSocket {
  return new OrderSocket({
    url: WS_URL,
    getToken: async () =>
      (await apiPost<{ token: string }>("/api/v1/realtime/handshake", {})).token,
    onMessage: handlers.onMessage,
    onOpen: handlers.onOpen,
    onClose: handlers.onClose,
  });
}
