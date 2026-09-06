"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useRef, useState } from "react";

import type { PaymentOut } from "@/lib/orders-types";

import { buttonStyles } from "@/lib/button";
import { ApiError, apiFetch } from "@/lib/client";
import {
  AUTO_OPEN_BUDGET_MS,
  consumeAutoOpen,
  hrefWithoutAutoOpen,
  isAutoOpenRequested,
  openAcquirer,
  resumableIntentUrl,
} from "@/lib/payment-return";

/**
 * Whether the API answered "there is no live intent for this order" — the
 * ordinary reply for an order that is already paid, or never got an intent.
 *
 * Everything else is a failure we cannot interpret: a 5xx, or a dropped
 * mobile connection where `fetch` itself rejected and there is no status to
 * read at all. Those must be visible and retryable — rendering nothing for
 * them leaves a buyer who came back from the bank app unpaid staring at a
 * `pending_payment` order with no button and no explanation, which is the
 * dead end this component exists to remove.
 */
function isNoActivePayment(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

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
    // paid, or the intent was never created) — nothing to retry. Any other
    // failure is surfaced with a retry button instead (see `isNoActivePayment`).
    retry: false,
    staleTime: 30_000,
    // An invoice can die while the order stays `pending_payment` — the
    // acquirer voids it, or the buyer cancels inside the bank app — and the
    // button would then point at a dead one (no money risk: all three
    // callbacks refuse it; but the buyer meets an error at the bank instead
    // of a fresh intent). Re-read on a slow beat rather than riding the
    // order's own 8s poll: the answer changes far more rarely than the
    // order's status, and every waiting buyer pays for this endpoint.
    refetchInterval: awaitingPayment ? 30_000 : false,
  });

  // `awaitingPayment` is part of the answer, not just a fetch gate: react-query
  // keeps the last payment in cache when a query is disabled, so an order that
  // has since been paid would otherwise still be offering a live pay button
  // off a stale row.
  const payUrl = awaitingPayment ? resumableIntentUrl(payment.data) : null;
  const autoOpen = isAutoOpenRequested(params);

  // When this page became the buyer's screen. The auto-open is the tail of
  // their «Оплатить» tap and expires with it — see `AUTO_OPEN_BUDGET_MS`.
  const arrivedAt = useRef(Date.now());
  // Only there to force the re-render that takes the "opening…" line down at
  // the deadline; the open itself is decided on the clock below, so a payment
  // landing in the same tick as this timer cannot slip through on stale state.
  const [openWindowClosed, setOpenWindowClosed] = useState(false);
  useEffect(() => {
    if (!autoOpen) return;
    const timer = setTimeout(() => {
      setOpenWindowClosed(true);
    }, AUTO_OPEN_BUDGET_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [autoOpen]);

  // Latch #1 of three (see `lib/payment-return.ts`): one open per mount, set
  // before anything else can throw so a re-render on the way cannot re-enter.
  const opened = useRef(false);
  useEffect(() => {
    // Nothing to open yet — wait for the payment rather than spending the
    // one-shot on an empty hand.
    if (!autoOpen || payUrl === null || opened.current) return;
    opened.current = true;
    const inTime = Date.now() - arrivedAt.current <= AUTO_OPEN_BUDGET_MS;
    const first = consumeAutoOpen(orderId);
    // Strip the flag first: this is the URL the buyer comes back to. Wrapped
    // like both panels' `router.push`, and for the same reason — the one-shot
    // is already spent on the line above, so a throw here must not take the
    // open down with it. (Failing to strip is survivable on its own: the
    // `sessionStorage` mark still refuses a second open.)
    try {
      router.replace(hrefWithoutAutoOpen(pathname, params), { scroll: false });
    } catch {
      /* see above — the mark is what actually holds */
    }
    if (first && inTime) openAcquirer(payUrl);
  }, [autoOpen, payUrl, orderId, pathname, params, router]);

  if (payUrl !== null) {
    return (
      <a href={payUrl} className={buttonStyles({ size: "lg", className: "w-full" })}>
        {t("payNow")}
        <ArrowUpRight size={17} strokeWidth={2.6} aria-hidden />
      </a>
    );
  }

  // Past this point there is nothing to pay with. Only an order still
  // awaiting payment has anything to say about that.
  if (!awaitingPayment) return null;

  if (payment.isError && !isNoActivePayment(payment.error)) {
    return (
      <div className="border-border bg-surface-1 space-y-3 rounded-xl border p-4 text-center">
        <p className="text-tx-mute text-sm">{t("payLoadError")}</p>
        <button
          type="button"
          onClick={() => {
            void payment.refetch();
          }}
          disabled={payment.isFetching}
          className={buttonStyles({ size: "sm" })}
        >
          {payment.isFetching ? t("loading") : t("retry")}
        </button>
      </div>
    );
  }

  // Arrived from checkout and still waiting on the answer: say the bank app is
  // coming, so the order page does not look finished while it is on its way.
  if (autoOpen && !openWindowClosed && payment.isPending) {
    return <p className="text-tx-mute text-sm">{t("openingBank")}</p>;
  }

  return null;
}
