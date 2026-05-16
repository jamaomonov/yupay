/**
 * Orders + payments: create, list, observe.
 *
 * Used by the miniapp pages to fetch the customer's history and to drive the
 * checkout flow on TopUp. Payment intent creation lives here too so the
 * "Buy" button is a single mutation from the UI's perspective.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError, apiGet, apiPost, newIdempotencyKey } from "./api";
import { useMe } from "./auth";

// --- DTOs -----------------------------------------------------------------

export type OrderStatus =
  | "pending_payment"
  | "paid"
  | "fulfilling"
  | "fulfilled"
  | "delivered"
  | "cancelled"
  | "expired"
  | "refunded";

export interface OrderItemOut {
  id: string;
  sku_id: string;
  qty: number;
  unit_price_usd: string;
  fulfillment_state: string;
  fulfillment_data: Record<string, unknown>;
  supplier_order_id: string | null;
}

export interface OrderOut {
  id: string;
  status: OrderStatus;
  currency: string;
  total_usd: string;
  total_charged: string;
  fx_snapshot_id: string | null;
  expires_at: string;
  created_at: string;
  paid_at: string | null;
  fulfilled_at: string | null;
  delivered_at: string | null;
  cancelled_at: string | null;
  items: OrderItemOut[];
}

interface OrderListOut {
  items: OrderOut[];
}

export interface PaymentOut {
  id: string;
  order_id: string;
  provider: string;
  status: string;
  amount: string;
  currency: string;
  intent_url: string | null;
  external_id: string | null;
}

// --- hooks ----------------------------------------------------------------

export function useMyOrders() {
  const me = useMe();
  return useQuery<OrderOut[]>({
    queryKey: ["my-orders", me.data?.id ?? null],
    enabled: Boolean(me.data),
    queryFn: async () => {
      const data = await apiGet<OrderListOut>("/api/v1/orders");
      return data.items;
    },
    staleTime: 30_000,
  });
}

export interface CreateOrderInput {
  skuId: string;
  fulfillmentData: Record<string, unknown>;
  currency?: string;
}

export interface CheckoutResult {
  order: OrderOut;
  payment: PaymentOut;
}

/**
 * Checkout = create order + create payment intent. One mutation from the UI.
 * Provider defaults to ``mock`` while real acquirers are stubs (see ADR-0012).
 */
export function useCheckout() {
  const qc = useQueryClient();
  return useMutation<CheckoutResult, ApiError, CreateOrderInput & { provider?: string }>({
    mutationFn: async ({ skuId, fulfillmentData, currency = "USD", provider = "mock" }) => {
      const order = await apiPost<OrderOut>(
        "/api/v1/orders",
        {
          currency,
          items: [
            {
              sku_id: skuId,
              qty: 1,
              fulfillment_data: fulfillmentData,
            },
          ],
        },
        { idempotencyKey: newIdempotencyKey("order") },
      );
      const payment = await apiPost<PaymentOut>("/api/v1/payments/intents", {
        order_id: order.id,
        provider,
      });
      return { order, payment };
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["my-orders"] });
    },
  });
}

export function useOrder(orderId: string | undefined) {
  return useQuery<OrderOut>({
    queryKey: ["order", orderId],
    enabled: Boolean(orderId),
    queryFn: () => apiGet<OrderOut>(`/api/v1/orders/${orderId ?? ""}`),
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      if (!status) return false;
      // Poll while the order is in motion. Once terminal, stop.
      if (["pending_payment", "paid", "fulfilling", "fulfilled"].includes(status)) {
        return 3_000;
      }
      return false;
    },
  });
}

// Map an OrderOut to the prototype's flat history-row shape so the History page
// can stay close to its original markup.
export interface HistoryRow {
  id: string;
  gameSlug: string | null;
  amount: number;
  currency: string;
  date: string;
  status: "success" | "processing" | "failed";
  raw: OrderOut;
}

export function orderToHistoryRow(o: OrderOut): HistoryRow {
  const status: HistoryRow["status"] =
    o.status === "delivered"
      ? "success"
      : o.status === "fulfilled" || o.status === "paid" || o.status === "fulfilling"
        ? "processing"
        : o.status === "cancelled" || o.status === "expired"
          ? "failed"
          : "processing";
  return {
    id: o.id,
    // Items refer to SKUs by id; the UI doesn't know the brand slug without
    // joining catalog. We surface the SKU id and let the UI fall back to a
    // generic icon.
    gameSlug: null,
    amount: Number.parseFloat(o.total_charged) || 0,
    currency: o.currency,
    date: new Date(o.created_at).toLocaleString("ru", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }),
    status,
    raw: o,
  };
}
