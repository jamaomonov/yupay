"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { Fragment, useEffect, useState } from "react";

import type { OrderDetail } from "@/lib/types";

import { CopyButton } from "@/components/CopyButton";
import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { failureLabel, orderStatusLabel, orderTitle } from "@/lib/labels";
import { pathFor } from "@/lib/locale-href";
import { formatUsd, toCents } from "@/lib/money";
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
      .then(setOrder)
      .catch(() => {
        setMissing(true);
      });
  }, [id]);

  const refunded = order ? toCents(order.refunded_usd) : 0n;
  const recipient = order ? recipientLines(order.recipient, locale) : [];
  const delivered = order?.delivery ? visibleArtifactLines(order.delivery.artifact) : [];

  return (
    // A reading measure. These two run long forms, and a two-column grid
    // stretched to 1600px puts a label and its value half a screen apart.
    <div className="max-w-4xl">
      <Link
        href={pathFor(locale, "/cabinet/orders")}
        className="text-tx-mute inline-flex items-center gap-1.5 text-sm"
      >
        <ArrowLeft size={15} />
        {t("back")}
      </Link>

      {missing && <p className="text-tx-dim mt-8 text-sm">{t("notFound")}</p>}

      {order !== null && (
        <>
          <h1 className="mt-4 break-words text-2xl font-semibold tracking-tight">
            {/* «Заказ», singular — this screen is one order, not the list. */}
            {orderTitle(order, t("colOrder"))}
          </h1>
          {!order.merchant_order_id.startsWith("manual-") && (
            <p className="text-tx-dim mt-1 text-xs">
              {t("idLabel")}: {order.merchant_order_id}
            </p>
          )}

          {recipient.length > 0 && (
            <section className="border-border bg-card mt-6 rounded-xl border p-6">
              <h2 className="font-semibold">{t("recipient")}</h2>
              <dl className="mt-4 grid grid-cols-[auto_1fr_auto] items-baseline gap-x-3 gap-y-3">
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

          <section className="border-border bg-card mt-6 rounded-xl border p-6">
            <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
              <div>
                <dt className="text-tx-mute text-sm">{t("colStatus")}</dt>
                <dd className="mt-0.5 font-medium">{orderStatusLabel(order.status, t)}</dd>
              </div>
              <div>
                <dt className="text-tx-mute text-sm">{t("colPrice")}</dt>
                <dd className="mt-0.5 font-mono font-medium">
                  ${formatUsd(toCents(order.price_usd))}
                </dd>
              </div>
              {refunded > 0n && (
                <div>
                  <dt className="text-tx-mute text-sm">{t("colRefunded")}</dt>
                  <dd className="mt-0.5 font-mono font-medium">${formatUsd(refunded)}</dd>
                </div>
              )}
              <div>
                <dt className="text-tx-mute text-sm">{t("colCreated")}</dt>
                <dd className="mt-0.5">{formatMoment(order.created_at, locale)}</dd>
              </div>
              {order.delivered_at !== null && (
                <div>
                  <dt className="text-tx-mute text-sm">{t("deliveredAt")}</dt>
                  <dd className="mt-0.5">{formatMoment(order.delivered_at, locale)}</dd>
                </div>
              )}
            </dl>

            {order.failure_reason !== null && (
              <p className="border-border text-tx-mute mt-5 border-t pt-5 text-sm leading-relaxed">
                {failureLabel(order.failure_reason, t)}
              </p>
            )}

            <details className="border-border mt-5 border-t pt-5 text-sm">
              <summary className="text-tx-mute cursor-pointer select-none">
                {t("technical")}
              </summary>
              <dl className="mt-3 grid gap-x-8 gap-y-4 sm:grid-cols-2">
                <div>
                  <dt className="text-tx-mute text-sm">{t("ourId")}</dt>
                  <dd className="mt-1 flex items-center gap-2">
                    <span className="break-all font-mono text-xs">{order.order_id}</span>
                    <CopyButton value={order.order_id} label={t("copy")} done={t("copied")} />
                  </dd>
                </div>
                <div>
                  <dt className="text-tx-mute text-sm">{t("sku")}</dt>
                  <dd className="mt-0.5 break-all font-mono text-xs">{order.sku_id}</dd>
                </div>
              </dl>
            </details>
          </section>

          {delivered.length > 0 && (
            <section className="border-border bg-card mt-6 rounded-xl border p-6">
              <h2 className="font-semibold">{t("delivery")}</h2>
              {/* A two-column grid, not a fixed `w-28`: `supplier_reference`
                  is wider than 112px and overlapped its own value, which read
                  as `supplier_referencG2B-99182734` on screen. The copy
                  buttons line up in a column of their own instead of landing
                  at four different x positions. */}
              <dl className="mt-4 grid grid-cols-[auto_1fr_auto] items-baseline gap-x-3 gap-y-3">
                {delivered.map(({ key, value }) => (
                  <Fragment key={key}>
                    <dt className="text-tx-dim whitespace-nowrap font-mono text-xs">{key}</dt>
                    <dd className="min-w-0 break-all font-mono text-sm">{value}</dd>
                    <CopyButton value={value} label={t("copy")} done={t("copied")} />
                  </Fragment>
                ))}
              </dl>
            </section>
          )}

          {order.timeline.length > 0 && (
            <section className="border-border bg-card mt-6 rounded-xl border p-6">
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
        </>
      )}
    </div>
  );
}
