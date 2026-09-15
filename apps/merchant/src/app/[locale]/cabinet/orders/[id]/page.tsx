"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { pathFor } from "@/lib/locale-href";
import type { OrderDetail } from "@/lib/types";

import { CopyButton } from "@/components/CopyButton";
import { api } from "@/lib/api";
import { formatMoment } from "@/lib/datetime";
import { failureLabel, orderStatusLabel } from "@/lib/labels";
import { formatUsd, toCents } from "@/lib/money";

/**
 * Flatten a delivery artifact into copyable lines.
 *
 * The shape follows `artifact_kind` and the vocabulary grows, so this reads
 * whatever is there rather than switching on the kind: `code`, `codes`, a
 * receipt's fields. Anything that is not a string or a list of strings is
 * rendered as JSON — visible and copyable, which beats hiding it.
 */
function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function artifactLines(artifact: Record<string, unknown>): { key: string; value: string }[] {
  return Object.entries(artifact).flatMap(([key, value]) => {
    if (typeof value === "string") return [{ key, value }];
    if (isStringArray(value)) {
      return value.map((item, index) => ({ key: `${key}[${String(index)}]`, value: item }));
    }
    return [{ key, value: JSON.stringify(value) }];
  });
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

  return (
    <div>
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
          <h1 className="mt-4 break-all text-2xl font-semibold tracking-tight">
            {order.merchant_order_id}
          </h1>

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
          </section>

          {order.delivery !== null && (
            <section className="border-border bg-card mt-6 rounded-xl border p-6">
              <h2 className="font-semibold">{t("delivery")}</h2>
              <dl className="mt-4 space-y-3">
                {artifactLines(order.delivery.artifact).map(({ key, value }) => (
                  <div key={key} className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <dt className="text-tx-dim w-28 shrink-0 font-mono text-xs">{key}</dt>
                    <dd className="break-all font-mono text-sm">{value}</dd>
                    <CopyButton value={value} label={t("copy")} done={t("copied")} />
                  </div>
                ))}
              </dl>
            </section>
          )}

          {order.timeline.length > 0 && (
            <section className="border-border bg-card mt-6 rounded-xl border p-6">
              <h2 className="font-semibold">{t("timeline")}</h2>
              <ol className="mt-4 space-y-2.5">
                {order.timeline.map((entry) => (
                  <li
                    key={`${entry.event}-${entry.at}`}
                    className="flex flex-wrap items-baseline gap-x-3 text-sm"
                  >
                    <span className="font-mono text-xs">{entry.event}</span>
                    <span className="text-tx-dim">{formatMoment(entry.at, locale)}</span>
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
