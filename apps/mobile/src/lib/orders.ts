/**
 * Checkout and orders as the signed-in account: `POST /orders`, `POST /payments/intents`,
 * then the order read back. The app has no guest checkout — it opens on sign-in.
 */
import type { OrderListOut, OrderOut, PaymentOut, ProvidersOut } from "@yupay/api-client/types";
import { useQuery } from "@tanstack/react-query";
import { randomUUID } from "expo-crypto";

import { api } from "@/lib/api";
import {
  isLive,
  orderBody,
  returnUrl,
  stageOf,
  type OrderLine,
  type PayMethod,
} from "@/lib/checkout";
import { authRequest } from "@/lib/session";

const V1 = "/api/v1";
const WEB_URL = process.env.EXPO_PUBLIC_WEB_URL ?? "https://yupay.uz";

/** Recorded as the order's source (`orders.source`, migration 0102). */
const SURFACE = { "X-Yupay-Surface": "mobile" };
const JSON_BODY = { "Content-Type": "application/json" };

/** Hermes has no `crypto.randomUUID`. */
export function newKey(): string {
  return randomUUID();
}

/** Creates (or, with the same key, resumes) the order. */
export function createOrder(line: OrderLine, idempotencyKey: string): Promise<OrderOut> {
  return authRequest<OrderOut>(`${V1}/orders`, {
    method: "POST",
    headers: { ...JSON_BODY, ...SURFACE, "Idempotency-Key": idempotencyKey },
    body: JSON.stringify(orderBody(line)),
  });
}

/** A payment for the order through `provider`; the API reuses an open one. */
export function createIntent(input: {
  orderId: string;
  provider: PayMethod;
  locale: string;
}): Promise<PaymentOut> {
  return authRequest<PaymentOut>(`${V1}/payments/intents`, {
    method: "POST",
    headers: { ...JSON_BODY, ...SURFACE, "Idempotency-Key": newKey() },
    body: JSON.stringify({
      order_id: input.orderId,
      provider: input.provider,
      return_url: returnUrl(WEB_URL, input.locale, input.orderId),
    }),
  });
}

export function fetchOrder(orderId: string): Promise<OrderOut> {
  return authRequest<OrderOut>(`${V1}/orders/${encodeURIComponent(orderId)}`);
}

/** The account's orders, newest first. */
export function useAccountOrders() {
  return useQuery({
    queryKey: ["account", "orders"],
    queryFn: () => authRequest<OrderListOut>(`${V1}/orders`),
    staleTime: 15_000,
  });
}

/** Asked every 3 seconds while the order can still move by itself. */
export function useOrder(orderId: string) {
  return useQuery({
    queryKey: ["account", "order", orderId],
    queryFn: () => fetchOrder(orderId),
    refetchInterval: (query) =>
      query.state.data && !isLive(stageOf(query.state.data.status)) ? false : 3000,
  });
}

/** Acquirers under maintenance in the admin are not offered. */
export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: () => api.request<ProvidersOut>(`${V1}/payments/providers`),
    staleTime: 60_000,
  });
}
