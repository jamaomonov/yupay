/**
 * Factory for the order-updates WebSocket used by `useOrderSocket`.
 *
 * The URL is derived from the same `NEXT_PUBLIC_API_BASE_URL` the REST client
 * (`./client`) uses, swapping the scheme for `ws`/`wss`. Auth is a short-lived
 * (60s) handshake token minted by `POST /realtime/handshake`; `OrderSocket`
 * re-invokes `getToken` on every reconnect, so a stale/expired token never wedges
 * the connection.
 */
import { OrderSocket, type OrderUpdateMessage } from "@yupay/api-client";

import { apiFetch } from "./client";

const WS_URL =
  (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000")
    .replace(/^http/, "ws")
    .replace(/\/$/, "") + "/api/v1/realtime/ws/orders";

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
      (await apiFetch<{ token: string }>("/realtime/handshake", { method: "POST" })).token,
    onMessage: handlers.onMessage,
    // exactOptionalPropertyTypes: only set these keys when a handler was
    // actually provided, rather than assigning an explicit `undefined`.
    ...(handlers.onOpen !== undefined && { onOpen: handlers.onOpen }),
    ...(handlers.onClose !== undefined && { onClose: handlers.onClose }),
  });
}
