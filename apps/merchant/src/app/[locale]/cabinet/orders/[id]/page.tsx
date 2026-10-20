"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Fragment, useEffect, useState } from "react";

import type { OrderDetail } from "@/lib/types";

import { BrandMark } from "@/components/BrandMark";
import { CopyButton } from "@/components/CopyButton";
import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import {
  artifactLabel,
  failureLabel,
  orderStatusLabel,
  orderStatusTone,
  orderTitle,
} from "@/lib/labels";
import { pathFor } from "@/lib/locale-href";
import { dollars, toCents } from "@/lib/money";
import { recipientLines, visibleArtifactLines } from "@/lib/recipient";

/** `order.created` → «Создан», `order.paid` → the status label, and so on. */
function timelineLabel(event: string, t: (key: string) => string): string {
  const status = event.startsWith("order.") ? event.slice("order.".length) : event;
  if (status === "created") return t("colCreated");
  const label = orderStatusLabel(status, t);
  return label === status ? event : label;
}

export default function OrderDetailPage() {
  const t = useTranslations("merchant.orders");
  const { locale, id } = useParams<{ locale: string; id: string }>();
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    void api<OrderDetail>(`/orders/${encodeURIComponent(id)}`)
      .then((found) => {
        // A late success wins over an earlier failure (a retried or doubled
        // request): «not found» above a loaded order read as a contradiction.
        setMissing(false);
        setOrder(found);
      })
      .catch(() => {
        setMissing(true);
      });
  }, [id]);

  const refunded = order ? toCents(order.refunded_usd) : 0n;
  const recipient = order ? recipientLines(order.recipient, locale) : [];
  const delivered = order?.delivery ? visibleArtifactLines(order.delivery.artifact) : [];

  const card = "border-border bg-card rounded-xl border p-5";

  return (
    // Two columns on a wide screen: what the reseller acts on (who it was for, what was
    // handed over or why not) on the left, the money and the history on the right. One
    // column stretched to 900px left half the screen empty and the history below the fold.
    <div className="max-w-6xl">
      <Link
        href={pathFor(locale, "/cabinet/orders")}
        className="text-tx-mute hover:text-foreground inline-flex items-center gap-1.5 text-sm"
      >
        <ArrowLeft size={15} />
        {t("back")}
      </Link>

      {missing && order === null && <p className="text-tx-dim mt-8 text-sm">{t("notFound")}</p>}

      {order !== null && (
        <>
          <div className="mt-4 flex items-center gap-3.5">
            <BrandMark name={order.brand_name} logoUrl={order.brand_logo_url} />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <h1 className="min-w-0 break-words text-2xl font-semibold tracking-tight">
                  {/* «Заказ», singular — this screen is one order, not the list. */}
                  {orderTitle(order, t("colOrder"))}
                </h1>
                <span
                  className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${orderStatusTone(order.status)}`}
                >
                  {orderStatusLabel(order.status, t)}
                </span>
              </div>
              <p className="text-tx-dim mt-1 text-xs">
                {[
                  order.merchant_order_id.startsWith("manual-")
                    ? null
                    : `${t("idLabel")}: ${order.merchant_order_id}`,
                  formatMoment(order.created_at, locale),
                ]
                  .filter(Boolean)
                  .join(" · ")}
              </p>
            </div>
          </div>

          <div className="mt-6 grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_22rem]">
            <div className="space-y-5">
              {order.failure_reason !== null && (
                <section className="border-danger/30 bg-danger/5 rounded-xl border p-5">
                  <p className="text-sm leading-relaxed">{failureLabel(order.failure_reason, t)}</p>
                </section>
              )}

              {recipient.length > 0 && (
                <section className={card}>
                  <h2 className="font-semibold">{t("recipient")}</h2>
                  <dl className="mt-4 grid grid-cols-[auto_1fr_auto] items-center gap-x-4 gap-y-2.5">
                    {recipient.map((line) => (
                      <Fragment key={line.key}>
                        <dt className="text-tx-mute whitespace-nowrap text-sm">{line.label}</dt>
                        <dd className="min-w-0 break-all font-mono text-sm">{line.shown}</dd>
                        <CopyButton value={line.value} label={t("copy")} done={t("copied")} />
                      </Fragment>
                    ))}
                  </dl>
                </section>
              )}

              {delivered.length > 0 && (
                <section className={card}>
                  <h2 className="font-semibold">{t("delivery")}</h2>
                  {/* A two-column grid, not a fixed `w-28`: `supplier_reference`
                      is wider than 112px and overlapped its own value. The copy
                      buttons line up in a column of their own. */}
                  <dl className="mt-4 grid grid-cols-[auto_1fr_auto] items-center gap-x-4 gap-y-2.5">
                    {delivered.map(({ key, value }) => (
                      <Fragment key={key}>
                        <dt className="text-tx-mute whitespace-nowrap text-sm">
                          {artifactLabel(key, t)}
                        </dt>
                        <dd className="min-w-0 break-all font-mono text-sm">{value}</dd>
                        <CopyButton value={value} label={t("copy")} done={t("copied")} />
                      </Fragment>
                    ))}
                  </dl>
                </section>
              )}
            </div>

            <div className="space-y-5">
              <section className={card}>
                <dl className="space-y-3 text-sm">
                  <div className="flex items-baseline justify-between gap-4">
                    <dt className="text-tx-mute">{t("colPrice")}</dt>
                    <dd className="font-mono font-semibold tabular-nums">
                      {dollars(toCents(order.price_usd))}
                    </dd>
                  </div>
                  {refunded > 0n && (
                    <div className="flex items-baseline justify-between gap-4">
                      <dt className="text-tx-mute">{t("colRefunded")}</dt>
                      <dd className="text-primary-ink font-mono font-semibold tabular-nums">
                        {dollars(refunded)}
                      </dd>
                    </div>
                  )}
                  {order.delivered_at !== null && (
                    <div className="flex items-baseline justify-between gap-4">
                      <dt className="text-tx-mute">{t("deliveredAt")}</dt>
                      <dd>{formatMoment(order.delivered_at, locale)}</dd>
                    </div>
                  )}
                </dl>
              </section>

              {order.timeline.length > 0 && (
                <section className={card}>
                  <h2 className="font-semibold">{t("timeline")}</h2>
                  {/* Events are `order.<status>`; the status half is the same
                      vocabulary the badge uses, so it reads as words — the raw
                      code only for one we have never met. */}
                  <ol className="border-border mt-4 space-y-3 border-l pl-4">
                    {order.timeline.map((entry) => (
                      <li key={`${entry.event}-${entry.at}`} className="relative text-sm">
                        <span
                          aria-hidden
                          className="bg-border-2 absolute -left-[21px] top-1.5 h-2 w-2 rounded-full"
                        />
                        <p className="font-medium">{timelineLabel(entry.event, t)}</p>
                        <p className="text-tx-dim text-xs">{formatMoment(entry.at, locale)}</p>
                      </li>
                    ))}
                  </ol>
                </section>
              )}

              <details className={`${card} text-sm`}>
                <summary className="text-tx-mute cursor-pointer select-none">
                  {t("technical")}
                </summary>
                <dl className="mt-3 space-y-3">
                  <div>
                    <dt className="text-tx-mute text-xs">{t("ourId")}</dt>
                    <dd className="mt-1 flex items-center gap-2">
                      <span className="break-all font-mono text-xs">{order.order_id}</span>
                      <CopyButton value={order.order_id} label={t("copy")} done={t("copied")} />
                    </dd>
                  </div>
                  <div>
                    <dt className="text-tx-mute text-xs">{t("sku")}</dt>
                    <dd className="mt-0.5 break-all font-mono text-xs">{order.sku_id}</dd>
                  </div>
                </dl>
              </details>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
