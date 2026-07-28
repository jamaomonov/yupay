/**
 * Opens a single order-updates `OrderSocket` for the lifetime of a signed-in
 * session (no-op while signed out / anonymous browsing).
 *
 * Every message is a *nudge*, not a source of truth — the DB stays
 * authoritative, so each message carrying an `orderId` triggers a targeted
 * `invalidateQueries(["order", orderId])` refetch rather than writing the
 * payload straight into the cache. `order.delivered` additionally opens the
 * global delivered dialog (`useOrderDeliveredDialog`,
 * `components/OrderDeliveredDialog`).
 *
 * `order.failed` is intentionally NOT handled: fulfillment failures keep the
 * order at `fulfilling` for admin remediation, never a customer-facing status
 * (DOMAIN RULE) — so there is no failed-order UI anywhere in the Mini App.
 */
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import type { OrderUpdateMessage } from "@yupay/api-client";

import { useMe } from "@/lib/auth";
import { createOrderSocket } from "@/lib/realtime";
import { useOrderDeliveredDialog } from "@/store/useOrderDeliveredDialog";
import { useRealtimeStatus } from "@/store/useRealtimeStatus";

export interface OrderUpdateHandlers {
  invalidateOrder: (orderId: string) => void;
  openDelivered: (orderId: string) => void;
}

/**
 * Pure message router, split out of the hook so it can be unit-tested without
 * mounting a component (this app's Vitest setup runs in the `node`
 * environment — no DOM/React renderer wired up for hook tests).
 */
export function routeOrderUpdateMessage(
  message: OrderUpdateMessage,
  handlers: OrderUpdateHandlers,
): void {
  switch (message.type) {
    case "order.status_changed":
      handlers.invalidateOrder(message.orderId);
      break;
    case "order.delivered":
      handlers.invalidateOrder(message.orderId);
      handlers.openDelivered(message.orderId);
      break;
    case "order.failed":
    case "ping":
      break;
    default: {
      const exhaustive: never = message;
      void exhaustive;
    }
  }
}

function invalidateOrderQuery(queryClient: QueryClient, orderId: string): void {
  void queryClient.invalidateQueries({ queryKey: ["order", orderId] });
}

export function useOrderSocket(): void {
  const me = useMe();
  const queryClient = useQueryClient();
  const setConnected = useRealtimeStatus((s) => s.setConnected);
  const openDeliveredDialog = useOrderDeliveredDialog((s) => s.open);

  // Refs so the connect effect only depends on the signed-in user id —
  // reconnecting the socket whenever the query client or a store setter
  // identity changes would be wasteful (store setters from `create()` are
  // stable anyway, but the ref keeps the effect body honest about what
  // actually needs a reconnect).
  const queryClientRef = useRef(queryClient);
  queryClientRef.current = queryClient;
  const setConnectedRef = useRef(setConnected);
  setConnectedRef.current = setConnected;
  const openDeliveredDialogRef = useRef(openDeliveredDialog);
  openDeliveredDialogRef.current = openDeliveredDialog;

  // Key the socket lifecycle on the user id, not the `me.data` object
  // reference: a background ``["me"]`` refetch hands back a new object with
  // the same id, which must NOT tear down and re-handshake the socket.
  const userId = me.data?.id;
  useEffect(() => {
    if (!userId) return undefined;

    const handleMessage = (message: OrderUpdateMessage): void => {
      routeOrderUpdateMessage(message, {
        invalidateOrder: (orderId) => {
          invalidateOrderQuery(queryClientRef.current, orderId);
        },
        openDelivered: (orderId) => {
          openDeliveredDialogRef.current(orderId);
        },
      });
    };

    const socket = createOrderSocket({
      onMessage: handleMessage,
      onOpen: () => {
        setConnectedRef.current(true);
        // Catch-up refetch: a transition published in the sliver before the
        // server's Redis SUBSCRIBE completes is dropped, and polling is now
        // off — re-pull any mounted order query on every (re)connect.
        void queryClientRef.current.invalidateQueries({ queryKey: ["order"] });
      },
      onClose: () => {
        setConnectedRef.current(false);
      },
    });
    void socket.connect();

    return () => {
      socket.close();
      setConnectedRef.current(false);
    };
  }, [userId]);
}
