"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import type { GuestOrder } from "@/lib/guest-orders";

import { GuestOrderCard } from "@/components/order/GuestOrderCard";
import { buttonStyles } from "@/lib/button";
import { pathFor } from "@/lib/seo";

/**
 * Order history for a signed-out visitor, sourced entirely from this
 * browser's localStorage (see `lib/guest-orders.ts`) — the server has no
 * account to list against. Each stub is enriched into a full `OrderCard` by
 * `GuestOrderCard`, which fetches the order via a per-email guest token so
 * the guest list matches the logged-in list's look.
 */
export function GuestOrdersList({ orders, locale }: { orders: GuestOrder[]; locale: string }) {
  const t = useTranslations("web.orders");

  return (
    <>
      <h1 className="font-display mb-2 text-3xl font-bold tracking-[-0.02em]">
        {t("guestListTitle")}
      </h1>
      <p className="text-tx-dim mb-6 text-sm">{t("guestListHint")}</p>

      {orders.length === 0 ? (
        <div className="border-border bg-card rounded-2xl border p-10 text-center">
          <p className="text-tx-mute mb-5">{t("guestListEmpty")}</p>
          <Link href={pathFor(locale, "/store")} className={buttonStyles({ size: "sm" })}>
            {t("toCatalog")}
          </Link>
        </div>
      ) : (
        <ul className="space-y-3">
          {orders.map((o) => (
            <li key={o.orderId}>
              <GuestOrderCard entry={o} locale={locale} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
