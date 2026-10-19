/**
 * Guest checkout and order status over the storefront API — the web storefront's flow
 * (`apps/web/src/lib/gift-checkout.ts`): a guest token for the email, `POST /orders`,
 * `POST /payments/intents`, then the order read back with the same token.
 */
import type { OrderOut, PaymentOut, ProvidersOut } from "@yupay/api-client/types";
import { useQuery } from "@tanstack/react-query";
import { randomUUID } from "expo-crypto";

import { api } from "@/lib/api";
import {
  isLive,
  normaliseEmail,
  orderBody,
  returnUrl,
  stageOf,
  type OrderLine,
  type PayMethod,
} from "@/lib/checkout";

const V1 = "/api/v1";
const WEB_URL = process.env.EXPO_PUBLIC_WEB_URL ?? "https://yupay.uz";

/** Recorded as the order's source (`orders.source`, migration 0102). */
const SURFACE = { "X-Yupay-Surface": "mobile" };
const JSON_BODY = { "Content-Type": "application/json" };

/** A guest token lives 30 minutes on the server; reuse one for 20. */
const TOKEN_REUSE_MS = 20 * 60_000;
const tokens = new Map<string, { token: string; at: number }>();

async function guestToken(email: string): Promise<string> {
  const key = normaliseEmail(email);
  const cached = tokens.get(key);
  if (cached && Date.now() - cached.at < TOKEN_REUSE_MS) return cached.token;
  const out = await api.request<{ access_token: string }>(`${V1}/auth/guest`, {
    method: "POST",
    headers: { ...JSON_BODY, ...SURFACE },
    body: JSON.stringify({ email: key }),
  });
  tokens.set(key, { token: out.access_token, at: Date.now() });
  return out.access_token;
}

/** Hermes has no `crypto.randomUUID`. */
export function newKey(): string {
  return randomUUID();
}

/** Creates (or, with the same key, resumes) the order. */
export async function createOrder(line: OrderLine, idempotencyKey: string): Promise<OrderOut> {
  const token = await guestToken(line.email);
  return api.request<OrderOut>(`${V1}/orders`, {
    method: "POST",
    headers: {
      ...JSON_BODY,
      ...SURFACE,
      Authorization: `Guest ${token}`,
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify(orderBody(line)),
  });
}

/** A payment for the order through `provider`; the API reuses an open one. */
export async function createIntent(input: {
  orderId: string;
  email: string;
  provider: PayMethod;
  locale: string;
}): Promise<PaymentOut> {
  const token = await guestToken(input.email);
  const email = encodeURIComponent(normaliseEmail(input.email));
  return api.request<PaymentOut>(`${V1}/payments/intents?email=${email}`, {
    method: "POST",
    headers: {
      ...JSON_BODY,
      ...SURFACE,
      Authorization: `Guest ${token}`,
      "Idempotency-Key": newKey(),
    },
    body: JSON.stringify({
      order_id: input.orderId,
      provider: input.provider,
      return_url: returnUrl(WEB_URL, input.locale, input.orderId, input.email),
    }),
  });
}

export async function fetchOrder(orderId: string, email: string): Promise<OrderOut> {
  const token = await guestToken(email);
  return api.request<OrderOut>(`${V1}/orders/${encodeURIComponent(orderId)}`, {
    headers: { Authorization: `Guest ${token}`, "X-Guest-Email": normaliseEmail(email) },
  });
}

/** Asked every 3 seconds while the order can still move by itself. */
export function useOrder(orderId: string, email: string | null) {
  return useQuery({
    queryKey: ["order", orderId],
    queryFn: () => fetchOrder(orderId, email ?? ""),
    enabled: email !== null,
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
