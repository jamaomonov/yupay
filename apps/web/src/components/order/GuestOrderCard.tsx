"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";

import type { GuestOrder } from "@/lib/guest-orders";
import type { OrderOut } from "@/lib/orders-types";

import { OrderCard } from "@/components/order/OrderCard";
import { OrderCardSkeleton } from "@/components/order/OrderCardSkeleton";
import { apiFetch } from "@/lib/client";
import { mintGuestToken } from "@/lib/guest";
import { pathFor } from "@/lib/seo";

/**
 * Enriches a locally-stored `GuestOrder` stub (brand name + date only, see
 * `lib/guest-orders.ts`) into the same rich `OrderCard` the logged-in list
 * uses, by minting a per-email guest token and fetching the full order —
 * the exact auth pattern `OrderStatus` uses for a guest viewing their
 * order-status page. React Query dedupes the `["guest-token", email]` query
 * across cards that share an email, so a repeat visit only mints once.
 *
 * Falls back to the bare stub (brand + date + an "open" link) if the token
 * mint or the order fetch fails — e.g. an order that's aged out of the
 * guest-token lookup window — so the entry isn't just dropped from the list.
 */
export function GuestOrderCard({ entry, locale }: { entry: GuestOrder; locale: string }) {
  const t = useTranslations("web.orders");
  // Stored un-normalized at save time (whatever the buyer typed).
  const normalizedEmail = entry.email.trim().toLowerCase();

  const guestToken = useQuery({
    queryKey: ["guest-token", normalizedEmail],
    queryFn: () => mintGuestToken(normalizedEmail),
  });

  // `anonymous: true` stops apiFetch from overwriting Authorization with a
  // stale/absent Bearer header — the explicit Guest header below survives.
  const guestAuth = guestToken.data
    ? {
        anonymous: true as const,
        headers: {
          Authorization: `Guest ${guestToken.data}`,
          "X-Guest-Email": normalizedEmail,
        },
      }
    : undefined;

  const order = useQuery({
    queryKey: ["order", entry.orderId, normalizedEmail],
    enabled: Boolean(guestAuth),
    queryFn: () => {
      // `enabled` guarantees `guestAuth` is set whenever this actually runs;
      // the guard just satisfies the type checker.
      if (!guestAuth) throw new Error("guest order card: missing token");
      return apiFetch<OrderOut>(`/orders/${entry.orderId}`, guestAuth);
    },
  });

  const href = pathFor(
    locale,
    `/orders/${entry.orderId}?email=${encodeURIComponent(normalizedEmail)}`,
  );

  if (order.data) {
    return <OrderCard order={order.data} locale={locale} href={href} />;
  }

  if (guestToken.isError || order.isError) {
    return (
      <Link
        href={href}
        className="border-border bg-card hover:border-tx-dim flex items-center justify-between gap-3 rounded-2xl border p-3.5 transition"
      >
        <div className="min-w-0 flex-1">
          <p className="text-foreground truncate text-sm font-bold">{entry.brandName}</p>
          <p className="text-tx-dim mt-0.5 text-[11px]">
            {new Intl.DateTimeFormat(locale).format(new Date(entry.createdAt))}
          </p>
        </div>
        <span className="text-primary shrink-0 text-xs font-semibold">{t("open")}</span>
      </Link>
    );
  }

  // Loading (token mint or order fetch in flight) — a skeleton matching the
  // real card's shape so the list doesn't jump once data lands.
  return <OrderCardSkeleton />;
}
