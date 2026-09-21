"use client";

import { ArrowRight, LayoutGrid, Package, Wallet } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { OrderRow, OrdersPage, Summary } from "@/lib/types";

import { useCabinet } from "@/components/CabinetContext";
import { CopyButton } from "@/components/CopyButton";
import { EmptyState } from "@/components/EmptyState";
import { TodayStats } from "@/components/TodayStats";
import { api } from "@/lib/api";
import { orderStatusLabel, orderStatusTone, orderTitle } from "@/lib/labels";
import { pathFor } from "@/lib/locale-href";
import { formatUsd, toCents } from "@/lib/money";

/** Enough to recognise "yes, my integration is placing orders" at a glance. */
const RECENT = 6;

export default function Dashboard() {
  const t = useTranslations("merchant.cabinet");
  const tOrders = useTranslations("merchant.orders");
  const { locale } = useParams<{ locale: string }>();
  const { profile } = useCabinet();
  const [recent, setRecent] = useState<OrderRow[] | null>(null);
  const [today, setToday] = useState<Summary | null>(null);

  useEffect(() => {
    void api<OrdersPage>(`/orders?limit=${String(RECENT)}`)
      .then((page) => {
        setRecent(page.items);
      })
      .catch(() => {
        setRecent([]);
      });
    // Midnight on the viewer's clock, as Orders does — the server does not
    // decide what "today" is.
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    void api<Summary>(`/summary?since=${encodeURIComponent(midnight.toISOString())}`)
      .then(setToday)
      .catch(() => undefined);
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
          <p className="flex items-center gap-2 font-medium">
            <Wallet aria-hidden size={17} className="text-primary-ink shrink-0" />
            {t("balanceEmptyTitle")}
          </p>
          <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("balanceEmptyBody")}</p>
          {/* The account number and what to put in the message. Without them
              the button opens a Telegram chat the operator stares at with
              nothing to say — `merchant_id` was fetched and rendered nowhere,
              so they had no way to identify themselves even if they guessed
              what to write. This is the whole of the "I registered and got
              stuck" path, and it is two lines. */}
          <p className="text-tx-mute mt-3 text-sm leading-relaxed">{t("whatToSend")}</p>
          {profile?.merchant_id && (
            <p className="mt-2 flex items-center gap-2 text-sm">
              <span className="text-tx-dim">{t("accountRef")}:</span>
              <code className="font-mono text-xs">{profile.merchant_id}</code>
              <CopyButton value={profile.merchant_id} label={t("copy")} done={t("copied")} />
            </p>
          )}
          <a
            href="https://t.me/yupay_support"
            target="_blank"
            rel="noopener noreferrer"
            className="bg-primary text-primary-foreground rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold"
          >
            {t("requestDeposit")}
          </a>
        </section>
      )}

      <div className="mt-5">
        <TodayStats today={today} balance={balance === null ? "—" : `$${formatUsd(balance)}`} />
      </div>

      <section className="mt-4 grid gap-4 lg:grid-cols-3">
        <Link
          href={pathFor(locale, "/cabinet/catalog")}
          className="border-border bg-card-2 group rounded-xl border p-5 font-semibold"
        >
          <span className="flex items-center gap-2.5">
            <LayoutGrid aria-hidden size={18} className="text-primary-ink shrink-0" />
            {t("navCatalog")}
            <ArrowRight
              aria-hidden
              size={15}
              className="text-tx-dim ml-auto shrink-0 transition group-hover:translate-x-0.5"
            />
          </span>
        </Link>
        <div className="border-border bg-card rounded-xl border p-5 lg:col-span-2">
          <Link
            href={pathFor(locale, "/cabinet/orders")}
            className="text-tx-mute flex items-center gap-2 text-sm"
          >
            <Package aria-hidden size={15} className="text-tx-dim shrink-0" />
            {t("recentOrders")}
          </Link>
          {recent !== null && recent.length === 0 && (
            <EmptyState icon={Package} title={t("noOrders")} />
          )}
          <ul className="mt-3 space-y-2.5">
            {(recent ?? []).map((row) => (
              <li key={row.order_id} className="flex items-baseline justify-between gap-3 text-sm">
                <div className="min-w-0">
                  <Link
                    href={pathFor(
                      locale,
                      `/cabinet/orders/${encodeURIComponent(row.merchant_order_id)}`,
                    )}
                    className="block truncate underline-offset-4 hover:underline"
                  >
                    {orderTitle(row, tOrders("colOrder"))}
                  </Link>
                  {!row.merchant_order_id.startsWith("manual-") && (
                    <p className="text-tx-dim truncate text-xs">{row.merchant_order_id}</p>
                  )}
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${orderStatusTone(row.status)}`}
                >
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
