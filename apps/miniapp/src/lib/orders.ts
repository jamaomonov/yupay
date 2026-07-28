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
import { getActiveLocale, translate, translatePlural } from "./i18n/core";
import { isAppActive } from "./telegram";

import { useRealtimeStatus } from "@/store/useRealtimeStatus";

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
  /** Set only for a variable-amount SKU (Steam wallet top-up): the dollar
   *  amount the customer typed, already validated client-side against the
   *  SKU's bounds. Sent as a decimal string to avoid float round-trip —
   *  the server re-validates and re-prices from it; the client never sends
   *  a computed price. */
  amountUsd?: string;
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
    mutationFn: async ({
      skuId,
      fulfillmentData,
      currency = "USD",
      provider = "mock",
      amountUsd,
    }) => {
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
          detail: translate("checkout.providerUnavailable"),
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
              ...(amountUsd !== undefined ? { amount_usd: amountUsd } : {}),
            },
          ],
        },
        { idempotencyKey: newIdempotencyKey("order") },
      );
      const payment = await apiPost<PaymentOut>(
        "/api/v1/payments/intents",
        {
          order_id: order.id,
          provider,
        },
        { idempotencyKey: newIdempotencyKey("payment") },
      );
      return { order, payment };
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["my-orders"] });
      // A wallet-funded checkout debits the balance synchronously inside the
      // same request. Refresh the wallet queries (header pill + wallet page +
      // finance tab — all share the ``["wallet", …]`` prefix) so the new
      // balance shows immediately instead of after the staleTime / a reload.
      // No-op cost for card/external providers: the refetch just returns the
      // unchanged balance.
      void qc.invalidateQueries({ queryKey: ["wallet"] });
    },
  });
}

/**
 * Decide the REST polling interval for `useOrder`, given the order's live
 * status and whether the app/realtime channel are already covering it.
 * Exported (pure, no hooks) so the gating logic is unit-testable without
 * mounting the hook.
 */
export function orderRefetchInterval(
  status: OrderStatus | undefined,
  opts: { appActive: boolean; realtimeConnected: boolean },
): number | false {
  if (!status) return false;
  // Minimised app: stop burning the customer's battery and our API on an
  // order nobody is watching. `activated` refetches immediately (App.tsx).
  if (!opts.appActive) return false;
  // The order-updates WebSocket is live: it nudges this query on every
  // change, so REST polling on top of it would just burn battery/API budget
  // for no fresher data.
  if (opts.realtimeConnected) return false;
  // Poll while the order is in motion. Once terminal, stop.
  return ["pending_payment", "paid", "fulfilling", "fulfilled"].includes(status) ? 3_000 : false;
}

export function useOrder(orderId: string | undefined) {
  const realtimeConnected = useRealtimeStatus((s) => s.connected);
  return useQuery<OrderOut>({
    queryKey: ["order", orderId],
    enabled: Boolean(orderId),
    queryFn: () => apiGet<OrderOut>(`/api/v1/orders/${orderId ?? ""}`),
    refetchInterval: (q) =>
      orderRefetchInterval(q.state.data?.status, {
        appActive: isAppActive(),
        realtimeConnected,
      }),
  });
}

/**
 * Fetch the in-flight payment intent for an order so the order-detail page
 * can show a «pay now» button when the order is still ``pending_payment``.
 * Only enabled while the parent order has a pending intent — once the order
 * walks to ``paid`` / ``refunded`` / ``cancelled`` the backend returns 404
 * and we stop asking.
 */
export function useActivePayment(
  orderId: string | undefined,
  parentStatus: OrderStatus | undefined,
) {
  return useQuery<PaymentOut, ApiError>({
    queryKey: ["payment", "by-order", orderId],
    enabled: Boolean(orderId) && parentStatus === "pending_payment",
    queryFn: () => apiGet<PaymentOut>(`/api/v1/payments/by-order/${orderId ?? ""}`),
    retry: false,
    staleTime: 30_000,
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
export function useDeliveries(orderId: string | undefined, parentStatus: OrderStatus | undefined) {
  return useQuery<DeliveryOut[]>({
    queryKey: ["deliveries", orderId],
    enabled: Boolean(orderId),
    queryFn: async () => {
      const data = await apiGet<DeliveryListOut>(`/api/v1/orders/${orderId ?? ""}/deliveries`);
      return data.items;
    },
    refetchInterval: () => {
      if (!parentStatus) return false;
      if (parentStatus === "delivered") return false;
      if (!isAppActive()) return false;
      return ["paid", "fulfilling", "fulfilled"].includes(parentStatus) ? 2_000 : false;
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
  status: "success" | "processing" | "failed" | "refunded";
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
      title: translate("orders.orderTitle", { id: o.id.slice(0, 8) }),
      subtitle: o.items.length > 0 ? translatePlural("orders.positions", o.items.length) : null,
      image: null,
      gameSlug: null,
    };
  }
  const denom = first.denomination ?? first.sku_code;
  const product = first.product_name || first.product_slug;
  // The "brand · denomination" pair is the most-useful one-glance summary.
  const head = first.brand_name ? `${first.brand_name} · ${denom}` : `${product} · ${denom}`;
  const title = extra > 0 ? `${head} +${extra}` : head;
  const subtitle =
    first.brand_name && product && product !== first.brand_name
      ? product
      : first.region && first.region !== "GLOBAL"
        ? translate("orders.region", { region: first.region })
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
      : o.status === "refunded"
        ? "refunded"
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
    date: new Date(o.created_at).toLocaleString(getActiveLocale(), {
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
