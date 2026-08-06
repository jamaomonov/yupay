"use client";

import { useQuery } from "@tanstack/react-query";
import { Star } from "lucide-react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { use } from "react";

import type { OrderListOut } from "@/lib/orders-types";

import { GuestOrdersList } from "@/components/order/GuestOrdersList";
import { OrderCard } from "@/components/order/OrderCard";
import { OrderListSkeleton } from "@/components/order/OrderCardSkeleton";
import { Skeleton } from "@/components/ui/Skeleton";
import { useAuth } from "@/lib/auth";
import { buttonStyles } from "@/lib/button";
import { apiFetch } from "@/lib/client";
import { listGuestOrders } from "@/lib/guest-orders";
import { getMyReviews } from "@/lib/reviews";
import { pathFor } from "@/lib/seo";

// Hide checkouts the customer never paid for — these clutter the history with
// "clicked Pay, didn't finish" rows (the scheduler eventually expires them).
const HIDDEN_STATUSES = new Set(["pending_payment", "expired"]);

export default function OrdersPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = use(params);
  const t = useTranslations("web.orders");
  const tr = useTranslations("web.brandReviews");
  const { user, isLoading: authLoading } = useAuth();

  const orders = useQuery({
    queryKey: ["orders"],
    queryFn: () => apiFetch<OrderListOut>("/orders"),
    enabled: Boolean(user),
  });

  // Orders the user has already reviewed (any brand) — suppresses the CTA.
  // Coarse per-order match: nearly every order is single-brand, and a repeat
  // submit is rejected server-side (409) anyway.
  const myReviews = useQuery({
    queryKey: ["my-reviews"],
    queryFn: () => getMyReviews(),
    enabled: Boolean(user),
  });
  const reviewedOrders = new Set((myReviews.data?.items ?? []).map((r) => r.order_id));

  if (authLoading) {
    return (
      <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
        {/* Auth resolves before we even know which list to render — show the
            heading + card placeholders so the page doesn't flash empty. */}
        <Skeleton className="mb-6 h-9 w-48 rounded-lg" />
        <OrderListSkeleton />
      </main>
    );
  }

  // Guests have no account to list orders against — fall back to this
  // browser's local order history instead of bouncing them to /login.
  if (!user) {
    return (
      <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
        <GuestOrdersList orders={listGuestOrders()} locale={locale} />
      </main>
    );
  }

  const items = (orders.data?.items ?? []).filter((o) => !HIDDEN_STATUSES.has(o.status));
  const settled = !orders.isLoading && !orders.isError;

  return (
    <main className="mx-auto max-w-[640px] px-4 pb-24 pt-[120px]">
      <h1 className="font-display mb-6 text-3xl font-bold tracking-[-0.02em]">{t("title")}</h1>

      {orders.isLoading && <OrderListSkeleton />}

      {orders.isError && <p className="text-sm text-red-400">{t("listError")}</p>}

      {settled && items.length === 0 && (
        <div className="border-border bg-card rounded-2xl border p-10 text-center">
          <p className="text-tx-mute mb-5">{t("empty")}</p>
          <Link href={pathFor(locale, "/store")} className={buttonStyles({ size: "sm" })}>
            {t("toCatalog")}
          </Link>
        </div>
      )}

      {items.length > 0 && (
        <ul className="space-y-3">
          {items.map((o) => (
            <li key={o.id}>
              <OrderCard order={o} locale={locale} href={pathFor(locale, `/orders/${o.id}`)} />
              {o.status === "delivered" &&
                !reviewedOrders.has(o.id) &&
                o.items[0]?.display?.brand_slug && (
                  <Link
                    href={pathFor(
                      locale,
                      `/store/${o.items[0].display.brand_slug}?order=${o.id}#reviews`,
                    )}
                    className="text-primary ml-4 mt-1.5 inline-flex items-center gap-1 text-xs font-semibold"
                  >
                    <Star size={12} />
                    {tr("writeCta")}
                  </Link>
                )}
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
