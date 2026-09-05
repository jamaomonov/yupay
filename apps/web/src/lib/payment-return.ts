"use client";

/**
 * Getting the buyer back from the bank.
 *
 * Checkout used to hand the browser the acquirer's URL directly
 * (`window.location.href = intent_url`). On a phone the OS claims that URL and
 * opens the bank's app, so **no browser navigation happens** — the tab is
 * still showing the product page. None of our acquirers return the customer to
 * us, so they come back by hand, land on the game they started from, and see
 * no sign that an order exists. Confirmed on a real `steam-gift` order
 * (2026-09-05): a valid Uzum `intent_url`, `payment.status = cancelled`,
 * `order.status = expired` — created, never paid, dead on the 10-minute expiry.
 *
 * So checkout now navigates to the **order page** and lets that page open the
 * acquirer, carrying a one-shot flag in the query string. The tab genuinely
 * becomes the order page before the bank app takes over, which is the whole
 * point: whatever the buyer does next, the page behind them is their order,
 * with a «Оплатить» button on it.
 *
 * The flag must fire at most once per arrival, or returning from the bank
 * would bounce the buyer straight back into it. Three independent guards, any
 * one of which is enough:
 *
 * 1. an in-component `useRef` latch — covers re-renders, polls, WS pushes and
 *    React StrictMode's double-invoked effects within one mount;
 * 2. this module's `consumeAutoOpen` — a `sessionStorage` mark per order, so a
 *    reload or a tab the browser evicted and restored does not re-fire either;
 * 3. stripping the flag out of the URL (`hrefWithoutAutoOpen`) the moment it
 *    is used, so the URL the buyer returns to no longer asks for anything.
 *
 * Only #2 survives a reload, and only #3 survives a fresh browser session — so
 * they are kept together rather than picking one.
 */

import type { PaymentOut } from "./orders-types";

/** Query param checkout sets on the order-page URL to ask it, once, to open
 *  the acquirer. Named for what the buyer is doing, since it is visible in
 *  their address bar for the moment before it is stripped. */
export const AUTO_OPEN_PARAM = "pay";
const AUTO_OPEN_VALUE = "1";

/** Per-order, per-tab record that the flag has already been spent. */
const SPENT_PREFIX = "yupay.web.autopay.";

/** The read side of `URLSearchParams`. `useSearchParams()` hands back a
 *  `ReadonlyURLSearchParams`, which is not assignable to `URLSearchParams`. */
export interface ReadableParams {
  get(name: string): string | null;
  toString(): string;
}

/**
 * The order-page href checkout should navigate to, asking that page to open
 * the acquirer once it is there.
 *
 * Everything already on the href is preserved — most importantly a guest's
 * `?email=`, which is how the order page (and `payments/routes.py`'s
 * `_resolve_actor`) knows who is asking. Adding a flag that is already there
 * changes nothing.
 */
export function withAutoOpen(trackHref: string): string {
  // A root-relative path; the base is only there because `URL` demands one.
  const url = new URL(trackHref, "http://order.local");
  url.searchParams.set(AUTO_OPEN_PARAM, AUTO_OPEN_VALUE);
  return `${url.pathname}${url.search}`;
}

/** Whether this navigation asked the order page to open the acquirer. */
export function isAutoOpenRequested(params: ReadableParams): boolean {
  return params.get(AUTO_OPEN_PARAM) === AUTO_OPEN_VALUE;
}

/** The same URL with the one-shot flag taken back out — what the order page
 *  rewrites its address to the moment it uses it, so a buyer returning from
 *  the bank app is not asked to go there again. */
export function hrefWithoutAutoOpen(pathname: string, params: ReadableParams): string {
  const next = new URLSearchParams(params.toString());
  next.delete(AUTO_OPEN_PARAM);
  const query = next.toString();
  return query === "" ? pathname : `${pathname}?${query}`;
}

/**
 * Claim the one-shot for this order in this tab. `true` the first time and
 * `false` ever after, so a reload that still carries the flag (the tab was
 * evicted before the URL rewrite landed) does not re-open the bank app.
 *
 * Storage being unavailable degrades to `true`: opening once too often in a
 * browser that refuses `sessionStorage` beats never opening at all, and the
 * in-mount latch plus the stripped URL still hold.
 */
export function consumeAutoOpen(orderId: string): boolean {
  try {
    const key = `${SPENT_PREFIX}${orderId}`;
    if (window.sessionStorage.getItem(key) === AUTO_OPEN_VALUE) return false;
    window.sessionStorage.setItem(key, AUTO_OPEN_VALUE);
  } catch {
    /* private mode / storage blocked — see the docstring */
  }
  return true;
}

/** Payment states where the buyer can still go and pay. Anything else —
 *  succeeded, failed, cancelled, refunded — is over, and offering to pay it
 *  would be a lie. (The API's `/payments/by-order/{id}` filters to the same
 *  two states; this is the client-side half of the same rule, so a cached or
 *  stale response cannot put a live button on a dead payment.) */
const RESUMABLE = new Set(["pending", "requires_action"]);

/**
 * The acquirer page for a payment the buyer can still complete, or `null`.
 *
 * `null` for a settled or dead payment, and for one with no hosted page at
 * all: `WalletGateway` charges the balance inside `create_intent` and comes
 * back with `intent_url: null`, which must never reach the deeplink path.
 */
export function resumableIntentUrl(payment: PaymentOut | undefined): string | null {
  if (!payment || !RESUMABLE.has(payment.status)) return null;
  return payment.intent_url;
}

/**
 * Hand the tab to the acquirer.
 *
 * An assignment rather than `window.open`, because this runs from an effect
 * rather than a click and a popup blocker would eat the new window. On a phone
 * the OS intercepts the URL and opens the bank app, leaving this tab on the
 * order page — which is exactly what we want and why the navigation happens
 * from there. On a desktop it navigates to the acquirer's hosted page, whose
 * `return_url` is that same order page.
 *
 * Its own exported function so tests have a seam: assigning `location.href`
 * under jsdom is a "Not implemented: navigation" error, not a behaviour.
 */
export function openAcquirer(url: string): void {
  window.location.href = url;
}
