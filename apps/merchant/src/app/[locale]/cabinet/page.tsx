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
import { ListSkeleton } from "@/components/ListSkeleton";
import { TodayStats } from "@/components/TodayStats";
import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { orderStatusLabel, orderStatusTone, orderTitle } from "@/lib/labels";
import { pathFor } from "@/lib/locale-href";
import { formatUsd, toCents } from "@/lib/money";

/** Enough to recognise "yes, my integration is placing orders" at a glance. */
const RECENT = 6;

export default function Dashboard() {
  const t = useTranslations("merchant.cabinet");
  const tOrders = useTranslations("merchant.orders");
  const { locale } = useParams<{ locale: string }>();
  const tTop = useTranslations("merchant.topUp");
  const { catalog, profile, p2p } = useCabinet();
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

  const selfServe = p2p?.enabled === true;
  const balance = profile ? toCents(profile.balance_usd) : null;

  return (
    <div>
      <h1 className="font-display text-xl font-semibold tracking-tight">{profile?.title ?? " "}</h1>

      {/* Held until `/p2p/status` answers, so the support copy never flashes
          before the top-up button. */}
      {balance === 0n && p2p !== null && (
        // The one thing a fresh account needs to be told, and the spec's whole
        // onboarding shape: the catalog is open, buying waits on support. Said
        // without naming the mechanism — no "deposit through support" process
        // detail on a customer-facing surface.
        <section className="border-border bg-card mt-5 rounded-xl border p-6">
          <p className="flex items-center gap-2 font-medium">
            <Wallet aria-hidden size={17} className="text-primary-ink shrink-0" />
            {t("balanceEmptyTitle")}
          </p>
          <p className="text-tx-mute mt-1.5 text-sm leading-relaxed">
            {selfServe ? tTop("emptyBody") : t("balanceEmptyBody")}
          </p>
          {/* The account number and what to put in the message. Without them
              the button opens a Telegram chat the operator stares at with
              nothing to say — `merchant_id` was fetched and rendered nowhere,
              so they had no way to identify themselves even if they guessed
              what to write. This is the whole of the "I registered and got
              stuck" path, and it is two lines. */}
          {!selfServe && (
            <p className="text-tx-mute mt-3 text-sm leading-relaxed">{t("whatToSend")}</p>
          )}
          {!selfServe && profile?.merchant_id && (
            <p className="mt-2 flex items-center gap-2 text-sm">
              <span className="text-tx-dim">{t("accountRef")}:</span>
              <code className="font-mono text-xs">{profile.merchant_id}</code>
              <CopyButton value={profile.merchant_id} label={t("copy")} done={t("copied")} />
            </p>
          )}
          {selfServe ? (
            <Link
              href={pathFor(locale, "/cabinet/top-up")}
              className="bg-primary text-primary-foreground rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold"
            >
              {tTop("title")}
            </Link>
          ) : (
            <a
              href="https://t.me/yupay_support"
              target="_blank"
              rel="noopener noreferrer"
              className="bg-primary text-primary-foreground rounded-btn mt-4 inline-flex px-4 py-2 text-sm font-semibold"
            >
              {t("requestDeposit")}
            </a>
          )}
        </section>
      )}

      <div className="mt-5">
        <TodayStats today={today} balance={balance === null ? "—" : `$${formatUsd(balance)}`} />
      </div>

      {/* `grid-cols-1` and `min-w-0`: an implicit track sizes to its widest content, and
          on a phone the logo grid pushed both cards 20px past the screen's edge. */}
      <section className="mt-4 grid grid-cols-1 items-start gap-4 lg:grid-cols-3">
        {/* The catalog card was a lone link that stretched to the height of
            the orders list beside it — a tall empty box. The brands themselves
            are the useful shortcut: one tap from here to a manual order. */}
        <div className="border-border bg-card min-w-0 rounded-xl border p-5">
          <Link
            href={pathFor(locale, "/cabinet/catalog")}
            className="group flex items-center gap-2 text-sm font-semibold"
          >
            <LayoutGrid aria-hidden size={16} className="text-primary-ink shrink-0" />
            {t("navCatalog")}
            <ArrowRight
              aria-hidden
              size={15}
              className="text-tx-dim ml-auto shrink-0 transition group-hover:translate-x-0.5"
            />
          </Link>
          <ul className="mt-4 grid grid-cols-4 gap-3 sm:grid-cols-6 lg:grid-cols-3">
            {(catalog?.brands ?? []).slice(0, 12).map((brand) => (
              <li key={brand.brand_id}>
                <Link
                  href={pathFor(locale, `/cabinet/catalog/${brand.slug}`)}
                  className="group flex flex-col items-center gap-1.5 text-center"
                >
                  <span className="bg-card-2 border-border group-hover:border-border-2 block h-12 w-12 overflow-hidden rounded-xl border transition">
                    {brand.logo_url !== null && (
                      /* eslint-disable-next-line @next/next/no-img-element -- an
                         operator-entered absolute URL, as in the catalog grid. */
                      <img src={brand.logo_url} alt="" className="h-full w-full object-cover" />
                    )}
                  </span>
                  <span className="text-tx-mute line-clamp-2 w-full text-[11px] leading-tight">
                    {brand.name}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <div className="border-border bg-card min-w-0 rounded-xl border p-5 lg:col-span-2">
          <Link
            href={pathFor(locale, "/cabinet/orders")}
            className="text-tx-mute flex items-center gap-2 text-sm"
          >
            <Package aria-hidden size={15} className="text-tx-dim shrink-0" />
            {t("recentOrders")}
          </Link>
          {recent === null && <ListSkeleton rows={3} className="mt-3 border-0 bg-transparent" />}
          {recent !== null && recent.length === 0 && (
            <EmptyState icon={Package} title={t("noOrders")} />
          )}
          <ul className="mt-3 space-y-1.5">
            {(recent ?? []).map((row) => (
              <li key={row.order_id} className="text-sm">
                {/* Name and amount on one line, status and time on the next:
                    the badge used to float mid-row at a different x on every
                    line, and nothing said when the order was placed. */}
                <Link
                  href={pathFor(
                    locale,
                    `/cabinet/orders/${encodeURIComponent(row.merchant_order_id)}`,
                  )}
                  className="hover:bg-card-2 -mx-2 block rounded-lg px-2 py-1.5"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="min-w-0 truncate font-medium">
                      {orderTitle(row, tOrders("colOrder"))}
                    </span>
                    <span className="shrink-0 font-mono text-xs">
                      ${formatUsd(toCents(row.price_usd))}
                    </span>
                  </div>
                  <div className="mt-1 flex items-center gap-2 text-xs">
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${orderStatusTone(row.status)}`}
                    >
                      {orderStatusLabel(row.status, tOrders)}
                    </span>
                    <span className="text-tx-dim truncate">
                      {formatMoment(row.created_at, locale)}
                      {row.merchant_order_id.startsWith("manual-")
                        ? ""
                        : ` · ${row.merchant_order_id}`}
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      </section>
    </div>
  );
}
