"use client";

import { formatMoney } from "@yupay/utils";
import { useLocale, useTranslations } from "next-intl";

import { PaymentProviderBadge } from "./PaymentProviderBadge";

import type { OrderOut } from "@/lib/orders-types";
import type { ReactNode } from "react";

function fmtDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

/** One right-aligned spec row inside the summary card. */
function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-2.5">
      <dt className="text-tx-mute text-sm">{label}</dt>
      <dd className="text-tx-mute text-right text-sm tabular-nums">{children}</dd>
    </div>
  );
}

export function OrderSummary({ order }: { order: OrderOut }) {
  const t = useTranslations("web.orders");
  const locale = useLocale();
  return (
    <dl className="border-border bg-card-2/50 divide-border divide-y rounded-xl border">
      {/* Money is the emphasis — a larger tabular-mono amount, its own row. */}
      <div className="flex items-center justify-between gap-4 px-4 py-3.5">
        <dt className="text-tx-mute text-sm">{t("total")}</dt>
        <dd className="text-foreground font-mono text-lg font-bold tabular-nums">
          {formatMoney(order.total_charged, order.currency, locale)}
        </dd>
      </div>

      {order.payment_provider ? (
        <Row label={t("paidWith")}>
          <PaymentProviderBadge provider={order.payment_provider} />
        </Row>
      ) : null}

      <Row label={t("createdAt")}>{fmtDate(order.created_at, locale)}</Row>

      {order.paid_at ? <Row label={t("paidAt")}>{fmtDate(order.paid_at, locale)}</Row> : null}

      {order.delivered_at ? (
        <Row label={t("deliveredAt")}>{fmtDate(order.delivered_at, locale)}</Row>
      ) : null}
    </dl>
  );
}
