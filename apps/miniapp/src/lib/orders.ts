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

export type ProductKind = "top_up" | "voucher";

export interface OrderItemDisplay {
  brand_slug: string;
  brand_name: string;
  product_slug: string;
  product_name: string;
  product_kind: ProductKind;
  sku_code: string;
  denomination: string | null;
  region: string | null;
  image_url: string | null;
}

export interface OrderItemOut {
  id: string;
  sku_id: string;
  qty: number;
  unit_price_usd: string;
  fulfillment_state: string;
  fulfillment_data: Record<string, unknown>;
  supplier_order_id: string | null;
  display: OrderItemDisplay | null;
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

interface ProvidersOut {
  providers: string[];
}

/**
 * Live payment-provider slugs (those whose ``gateway.available`` is true on
 * the backend). Stubs like ``click`` / ``yookassa`` / ``crypto`` are absent
 * until integrated, so the UI can grey them out instead of letting users
 * create an orphan order followed by a failed intent.
 */
export function useAvailableProviders() {
  return useQuery<string[]>({
    queryKey: ["payments", "providers"],
    queryFn: async () => {
      const data = await apiGet<ProvidersOut>("/api/v1/payments/providers");
      return data.providers;
    },
    staleTime: 60_000,
  });
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
  /** Order currency. The backend snapshots the FX rate at order time for any
   *  non-USD value so the total stays frozen even if the rate moves later. */
  currency?: string;
}

export interface CheckoutResult {
  order: OrderOut;
  payment: PaymentOut;
}

/**
 * Checkout = create order + create payment intent. One mutation from the UI.
 * Provider defaults to ``mock`` while real acquirers are stubs (see ADR-0012).
 *
 * The mutation *first* resolves the live-providers list (hit cache if fresh,
 * otherwise fetch) and refuses to create an order when the requested provider
 * isn't available. Without that guard a fast tap would race the providers
 * useQuery hook on the calling page and leave an orphan ``pending_payment``
 * order whenever the user picked a stub gateway.
 */
export function useCheckout() {
  const qc = useQueryClient();
  return useMutation<CheckoutResult, ApiError, CreateOrderInput & { provider?: string }>({
    mutationFn: async ({ skuId, fulfillmentData, currency = "USD", provider = "mock" }) => {
      const live = await qc.fetchQuery<string[]>({
        queryKey: ["payments", "providers"],
        queryFn: async () => {
          const data = await apiGet<ProvidersOut>("/api/v1/payments/providers");
          return data.providers;
        },
        staleTime: 60_000,
      });
      if (!live.includes(provider)) {
        throw new ApiError(409, "Conflict", {
          detail: "Способ оплаты временно недоступен",
        });
      }
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

// --- deliveries -----------------------------------------------------------

export type ArtifactKind = "voucher_code" | "topup_receipt" | "license_key";

export interface DeliveryOut {
  id: string;
  order_item_id: string;
  channel: string;
  artifact_kind: ArtifactKind;
  artifact: Record<string, unknown>;
  delivered_at: string;
}

interface DeliveryListOut {
  items: DeliveryOut[];
}

/**
 * Fetch delivery artifacts (codes / receipts) for an order.
 *
 * Polls while the parent order is still in motion so the success page can
 * surface fresh artifacts the moment fulfilment lands them.
 */
export function useDeliveries(
  orderId: string | undefined,
  parentStatus: OrderStatus | undefined,
) {
  return useQuery<DeliveryOut[]>({
    queryKey: ["deliveries", orderId],
    enabled: Boolean(orderId),
    queryFn: async () => {
      const data = await apiGet<DeliveryListOut>(
        `/api/v1/orders/${orderId ?? ""}/deliveries`,
      );
      return data.items;
    },
    refetchInterval: () => {
      if (!parentStatus) return false;
      if (parentStatus === "delivered") return false;
      return ["paid", "fulfilling", "fulfilled"].includes(parentStatus)
        ? 2_000
        : false;
    },
  });
}

// Map an OrderOut to the flat history-row shape used by the History page.
export interface HistoryRow {
  id: string;
  gameSlug: string | null;
  title: string;
  subtitle: string | null;
  imageUrl: string | null;
  itemsCount: number;
  amount: number;
  currency: string;
  date: string;
  status: "success" | "processing" | "failed";
  raw: OrderOut;
}

function summariseOrder(o: OrderOut): {
  title: string;
  subtitle: string | null;
  image: string | null;
  gameSlug: string | null;
} {
  const first = o.items[0]?.display ?? null;
  const extra = o.items.length - 1;
  if (!first) {
    return {
      title: `Заказ ${o.id.slice(0, 8)}`,
      subtitle: o.items.length > 0 ? `${o.items.length} поз.` : null,
      image: null,
      gameSlug: null,
    };
  }
  const denom = first.denomination ?? first.sku_code;
  const product = first.product_name || first.product_slug;
  // The "brand · denomination" pair is the most-useful one-glance summary.
  const head = first.brand_name
    ? `${first.brand_name} · ${denom}`
    : `${product} · ${denom}`;
  const title = extra > 0 ? `${head} +${extra}` : head;
  const subtitle =
    first.brand_name && product && product !== first.brand_name
      ? product
      : first.region && first.region !== "GLOBAL"
        ? `регион ${first.region}`
        : null;
  return {
    title,
    subtitle,
    image: first.image_url,
    gameSlug: first.brand_slug || null,
  };
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
  const summary = summariseOrder(o);
  return {
    id: o.id,
    gameSlug: summary.gameSlug,
    title: summary.title,
    subtitle: summary.subtitle,
    imageUrl: summary.image,
    itemsCount: o.items.length,
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
