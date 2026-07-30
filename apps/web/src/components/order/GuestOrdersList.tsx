"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import type { GuestOrder } from "@/lib/guest-orders";

import { buttonStyles } from "@/lib/button";
import { pathFor } from "@/lib/seo";

/**
 * Order history for a signed-out visitor, sourced entirely from this
 * browser's localStorage (see `lib/guest-orders.ts`) — the server has no
 * account to list against. Each entry links to the public order-status page
 * with a `?email=` suffix so that page can authenticate the guest via their
 * order-scoped token (see `OrderStatus`).
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
          {orders.map((o) => {
            // Stored un-normalized at save time (whatever the buyer typed) —
            // normalize before echoing it back as a guest-auth query param.
            const email = o.email.trim().toLowerCase();
            return (
              <li key={o.orderId}>
                <Link
                  href={pathFor(locale, `/orders/${o.orderId}?email=${encodeURIComponent(email)}`)}
                  className="border-border bg-card hover:border-tx-dim flex items-center justify-between gap-4 rounded-2xl border p-4 transition"
                >
                  <p className="text-foreground truncate font-semibold">{o.brandName}</p>
                  <p className="text-tx-dim shrink-0 text-xs">
                    {new Intl.DateTimeFormat(locale).format(new Date(o.createdAt))}
                  </p>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
