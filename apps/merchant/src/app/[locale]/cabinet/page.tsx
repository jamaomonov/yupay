"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { OrderRow, OrdersPage } from "@/lib/types";

import { useCabinet } from "@/components/CabinetContext";
import { api } from "@/lib/api";
import { orderStatusLabel } from "@/lib/labels";
import { formatUsd, toCents } from "@/lib/money";

/** Enough to recognise "yes, my integration is placing orders" at a glance. */
const RECENT = 6;

export default function Dashboard() {
  const t = useTranslations("merchant.cabinet");
  const tOrders = useTranslations("merchant.orders");
  const { locale } = useParams<{ locale: string }>();
  const { profile } = useCabinet();
  const [recent, setRecent] = useState<OrderRow[] | null>(null);

  useEffect(() => {
    void api<OrdersPage>(`/orders?limit=${String(RECENT)}`)
      .then((page) => {
        setRecent(page.items);
      })
      .catch(() => {
        setRecent([]);
      });
  }, []);

  const balance = profile ? toCents(profile.balance_usd) : null;

  return (
    <div>
      <h1 className="font-display text-xl font-semibold tracking-tight">{profile?.title ?? " "}</h1>

      {balance === 0n && (
        // The one thing a fresh account needs to be told, and the spec's whole
        // onboarding shape: the catalog is open, buying waits on support. Said
        // without naming the mechanism — no "deposit through support" process
        // detail on a customer-facing surface.
        <section className="border-border bg-card mt-5 rounded-xl border p-6">
          <p className="font-medium">{t("balanceEmptyTitle")}</p>
          <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("balanceEmptyBody")}</p>
          <a
            href="https://t.me/yupay_support"
            className="bg-primary text-primary-foreground rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold"
          >
            {t("requestDeposit")}
          </a>
        </section>
      )}

      <section className="mt-5 grid gap-4 lg:grid-cols-3">
        <Link
          href={`/${locale}/cabinet/catalog`}
          className="border-border bg-card-2 rounded-xl border p-5 font-semibold"
        >
          {t("navCatalog")}
        </Link>
        <div className="border-border bg-card rounded-xl border p-5 lg:col-span-2">
          <Link href={`/${locale}/cabinet/orders`} className="text-tx-mute text-sm">
            {t("recentOrders")}
          </Link>
          {recent !== null && recent.length === 0 && (
            <p className="text-tx-dim mt-2 text-sm">{t("noOrders")}</p>
          )}
          <ul className="mt-3 space-y-2.5">
            {(recent ?? []).map((row) => (
              <li key={row.order_id} className="flex items-baseline justify-between gap-3 text-sm">
                <Link
                  href={`/${locale}/cabinet/orders/${encodeURIComponent(row.merchant_order_id)}`}
                  className="min-w-0 truncate underline-offset-4 hover:underline"
                >
                  {row.merchant_order_id}
                </Link>
                <span className="text-tx-dim shrink-0 text-xs">
                  {orderStatusLabel(row.status, tOrders)}
                </span>
                <span className="shrink-0 font-mono text-xs">
                  ${formatUsd(toCents(row.price_usd))}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
