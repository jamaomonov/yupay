"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import type { OrderRow, OrdersPage, Profile, Summary } from "@/lib/types";

import { api } from "@/lib/api";
import { orderStatusLabel } from "@/lib/labels";
import { formatUsd, toCents } from "@/lib/money";

/** Enough to recognise "yes, my integration is placing orders" at a glance. */
const RECENT = 5;

export default function Dashboard() {
  const t = useTranslations("merchant.cabinet");
  const tOrders = useTranslations("merchant.orders");
  const { locale } = useParams<{ locale: string }>();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [recent, setRecent] = useState<OrderRow[] | null>(null);
  const [today, setToday] = useState<Summary | null>(null);

  useEffect(() => {
    void api<Profile>("/me")
      .then(setProfile)
      .catch(() => {
        // The shell's own session check has already redirected anyone without
        // one; a failure here is a revoked session mid-view, and the next
        // navigation resolves it. Nothing to say on this screen.
      });
    // Midnight on the *viewer's* clock, sent as UTC. The server does not
    // decide what "today" is — see the endpoint's docstring: a day derived
    // from the stored timezone would disagree with the dates rendered two
    // screens over, which are browser-local.
    const midnight = new Date();
    midnight.setHours(0, 0, 0, 0);
    void api<Summary>(`/summary?since=${encodeURIComponent(midnight.toISOString())}`)
      .then(setToday)
      .catch(() => undefined);
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
      <h1 className="text-2xl font-semibold tracking-tight">{profile?.title ?? " "}</h1>

      <section className="border-border bg-card mt-6 rounded-xl border p-6">
        <p className="text-tx-mute text-sm">{t("balance")}</p>
        <p className="mt-1 font-mono text-3xl font-semibold">
          {balance === null ? "—" : `$${formatUsd(balance)}`}
        </p>

        {balance === 0n && (
          // The one thing a fresh account needs to be told, and the spec's
          // whole onboarding shape: the catalog is open, buying waits on
          // support. Said without naming the mechanism — no "deposit through
          // support" process detail on a customer-facing surface.
          <div className="border-border mt-5 border-t pt-5">
            <p className="font-medium">{t("balanceEmptyTitle")}</p>
            <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">{t("balanceEmptyBody")}</p>
            <a
              href="https://t.me/yupay_support"
              className="border-border rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold"
            >
              {t("requestDeposit")}
            </a>
          </div>
        )}
      </section>

      <section className="border-border bg-card mt-6 rounded-xl border p-6">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="font-semibold">{t("todayTitle")}</p>
          <p className="text-tx-dim text-xs">{t("todayHint")}</p>
        </div>
        <dl className="mt-4 grid grid-cols-3 gap-4">
          <div>
            <dt className="text-tx-mute text-sm">{t("todayOrders")}</dt>
            <dd className="mt-0.5 font-mono text-2xl font-semibold">{today?.orders ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-tx-mute text-sm">{t("todayDelivered")}</dt>
            <dd className="mt-0.5 font-mono text-2xl font-semibold">{today?.delivered ?? "—"}</dd>
          </div>
          <div>
            <dt className="text-tx-mute text-sm">{t("todaySpend")}</dt>
            <dd className="mt-0.5 font-mono text-2xl font-semibold">
              {today === null
                ? "—"
                : `$${formatUsd(toCents(today.spend_usd))}${today.spend_capped ? "+" : ""}`}
            </dd>
          </div>
        </dl>
      </section>

      <section className="mt-6 grid gap-4 sm:grid-cols-2">
        <Link
          href={`/${locale}/cabinet/catalog`}
          className="border-border bg-card-2 rounded-xl border p-5 font-semibold"
        >
          {t("navCatalog")}
        </Link>
        <div className="border-border bg-card rounded-xl border p-5">
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
