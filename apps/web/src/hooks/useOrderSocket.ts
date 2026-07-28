"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, type ReactNode } from "react";

import type { OrderUpdateMessage } from "@yupay/api-client";

import { useAuth } from "@/lib/auth";
import { createOrderSocket } from "@/lib/realtime";
import { useOrderDeliveredModal } from "@/store/useOrderDeliveredModal";
import { useRealtimeStatus } from "@/store/useRealtimeStatus";

/**
 * Opens a single order-updates `OrderSocket` for the lifetime of an
 * authenticated session (no-op for guests).
 *
 * Every message is a *nudge*, not a source of truth — the DB stays
 * authoritative, so each message carrying an `orderId` triggers a targeted
 * `invalidateQueries(["order", orderId])` refetch rather than writing the
 * payload straight into the cache. `order.delivered` additionally opens the
 * delivered modal (`useOrderDeliveredModal`, UI built in a follow-up task).
 *
 * `order.failed` is intentionally NOT handled: fulfillment failures keep the
 * order at `fulfilling` for admin remediation, never a customer-facing status
 * (see the realtime module's domain rule) — so this MVP has no failed-order UI.
 */
export function useOrderSocket(): void {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const setConnected = useRealtimeStatus((s) => s.setConnected);
  const openDeliveredModal = useOrderDeliveredModal((s) => s.open);

  // Refs so the connect effect only depends on `user` — reconnecting the
  // socket whenever the query client or a store setter identity changes would
  // be wasteful (and store setters from `create()` are stable anyway, but the
  // ref keeps the effect body honest about what actually needs a reconnect).
  const queryClientRef = useRef(queryClient);
  queryClientRef.current = queryClient;
  const setConnectedRef = useRef(setConnected);
  setConnectedRef.current = setConnected;
  const openDeliveredModalRef = useRef(openDeliveredModal);
  openDeliveredModalRef.current = openDeliveredModal;

  // Key the socket lifecycle on the user id, not the `user` object reference:
  // a background ``["me"]`` refetch (e.g. after a profile edit) hands back a new
  // object with the same id, which must NOT tear down and re-handshake the socket.
  const userId = user?.id;
  useEffect(() => {
    if (!userId) return undefined;

    const handleMessage = (message: OrderUpdateMessage): void => {
      switch (message.type) {
        case "order.status_changed":
          void queryClientRef.current.invalidateQueries({
            queryKey: ["order", message.orderId],
          });
          break;
        case "order.delivered":
          void queryClientRef.current.invalidateQueries({
            queryKey: ["order", message.orderId],
          });
          openDeliveredModalRef.current(message.orderId);
          break;
        case "order.failed":
        case "ping":
          break;
        default: {
          const exhaustive: never = message;
          void exhaustive;
        }
      }
    };

    const socket = createOrderSocket({
      onMessage: handleMessage,
      onOpen: () => {
        setConnectedRef.current(true);
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

/** Mounts the order-updates socket for logged-in users. Renders no DOM of its own. */
export function RealtimeProvider({ children }: { children: ReactNode }): ReactNode {
  useOrderSocket();
  return children;
}
