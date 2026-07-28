import { describe, expect, it, vi } from "vitest";

import { routeOrderUpdateMessage } from "./useOrderSocket";

import type { OrderUpdateMessage } from "@yupay/api-client";

/**
 * `useOrderSocket` mounts an `OrderSocket` (browser `WebSocket`, `useEffect`,
 * TanStack Query context) that this app's `node`-environment Vitest setup
 * can't render. Its message-handling decision is a pure function
 * (`routeOrderUpdateMessage`) precisely so the routing logic — the part most
 * likely to regress — is unit-testable without a DOM.
 */
describe("routeOrderUpdateMessage", () => {
  it("invalidates the order query on order.status_changed", () => {
    const invalidateOrder = vi.fn();
    const openDelivered = vi.fn();

    routeOrderUpdateMessage(
      {
        type: "order.status_changed",
        orderId: "order-abc",
        status: "paid",
        at: "2026-07-28T00:00:00Z",
      },
      { invalidateOrder, openDelivered },
    );

    expect(invalidateOrder).toHaveBeenCalledWith("order-abc");
    expect(openDelivered).not.toHaveBeenCalled();
  });

  it("invalidates the order query and opens the delivered dialog on order.delivered", () => {
    const invalidateOrder = vi.fn();
    const openDelivered = vi.fn();

    routeOrderUpdateMessage(
      { type: "order.delivered", orderId: "order-xyz", payload: { kind: "code", data: {} } },
      { invalidateOrder, openDelivered },
    );

    expect(invalidateOrder).toHaveBeenCalledWith("order-xyz");
    expect(openDelivered).toHaveBeenCalledWith("order-xyz");
  });

  it("ignores ping and ignores order.failed — no failed-order UI (DOMAIN RULE)", () => {
    const invalidateOrder = vi.fn();
    const openDelivered = vi.fn();

    const messages: OrderUpdateMessage[] = [
      { type: "ping", at: "2026-07-28T00:00:00Z" },
      { type: "order.failed", orderId: "order-nope", reason: "supplier_error" },
    ];
    for (const message of messages) {
      routeOrderUpdateMessage(message, { invalidateOrder, openDelivered });
    }

    expect(invalidateOrder).not.toHaveBeenCalled();
    expect(openDelivered).not.toHaveBeenCalled();
  });
});
