"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef } from "react";

import type { ApiError } from "@/lib/client";
import type { PaymentOut } from "@/lib/orders-types";

import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";
import {
  consumeAutoOpen,
  hrefWithoutAutoOpen,
  isAutoOpenRequested,
  openAcquirer,
  resumableIntentUrl,
} from "@/lib/payment-return";

/** Guest credentials for the API, as `OrderStatus` builds them: a `Guest`
 *  bearer minted from the `?email=` link, sent instead of (never alongside) a
 *  stale session token. `undefined` for a signed-in buyer. */
export interface GuestAuth {
  anonymous: true;
  headers: Record<string, string>;
}

export interface OrderPayNowProps {
  orderId: string;
  /** Whether the order is still `pending_payment`. Nothing is fetched or shown
   *  for an order that has moved on — a paid, delivered, cancelled or expired
   *  order must never offer a pay button. */
  awaitingPayment: boolean;
  /** The guest's email from the `?email=` link; `undefined` when signed in. */
  email: string | undefined;
  auth: GuestAuth | undefined;
}

/**
 * The way back into paying an order.
 *
 * Two jobs, both missing until 2026-09-06. First, a **button**: the order page
 * never fetched the payment at all, so a buyer who left for the bank app and
 * came back had no way to reach the acquirer again and the order simply
 * expired. Second, the **arrival** half of the payment return — when checkout
 * pushed the browser here with `?pay=1`, this opens the acquirer itself, so
 * the tab the buyer returns to is already their order page rather than the
 * product they were about to buy. See `lib/payment-return.ts` for why the flag
 * is one-shot and how it is stopped from firing twice.
 */
export function OrderPayNow({ orderId, awaitingPayment, email, auth }: OrderPayNowProps) {
  const t = useTranslations("web.orders");
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  // Guests must send the email as a query param: `payments/routes.py`'s
  // `_resolve_actor` rebuilds the guest-token hash from it and refuses the
  // request without it. Signed-in buyers go on their Bearer alone.
  const path =
    email === undefined
      ? `/payments/by-order/${orderId}`
      : `/payments/by-order/${orderId}?email=${encodeURIComponent(email)}`;

  const payment = useQuery<PaymentOut, ApiError>({
    queryKey: ["payment", "by-order", orderId],
    // A guest's request is worthless without the minted `Guest` token that
    // rides in `auth` — asking early would just spend a 401.
    enabled: awaitingPayment && (email === undefined || auth !== undefined),
    queryFn: () => apiFetch<PaymentOut>(path, auth),
    // A 404 is the ordinary answer for an order with no live intent (already
    // paid, or the intent was never created) — nothing to retry.
    retry: false,
    staleTime: 30_000,
  });

  // `awaitingPayment` is part of the answer, not just a fetch gate: react-query
  // keeps the last payment in cache when a query is disabled, so an order that
  // has since been paid would otherwise still be offering a live pay button
  // off a stale row.
  const payUrl = awaitingPayment ? resumableIntentUrl(payment.data) : null;
  const autoOpen = isAutoOpenRequested(params);

  // Latch #1 of three (see `lib/payment-return.ts`): one open per mount, set
  // before anything else can throw so a re-render on the way cannot re-enter.
  const opened = useRef(false);
  useEffect(() => {
    // Nothing to open yet — wait for the payment rather than spending the
    // one-shot on an empty hand.
    if (!autoOpen || payUrl === null || opened.current) return;
    opened.current = true;
    const first = consumeAutoOpen(orderId);
    // Strip the flag first: this is the URL the buyer comes back to.
    router.replace(hrefWithoutAutoOpen(pathname, params), { scroll: false });
    if (first) openAcquirer(payUrl);
  }, [autoOpen, payUrl, orderId, pathname, params, router]);

  if (payUrl === null) return null;

  return (
    <a href={payUrl} className={buttonStyles({ size: "lg", className: "w-full" })}>
      {t("payNow")}
      <ArrowUpRight size={17} strokeWidth={2.6} aria-hidden />
    </a>
  );
}
