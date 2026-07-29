"use client";

import { formatMoney } from "@yupay/utils";
import { useLocale, useTranslations } from "next-intl";

import { PaymentProviderBadge } from "./PaymentProviderBadge";

import type { OrderOut } from "@/lib/orders-types";

function fmtDate(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(
    new Date(iso),
  );
}

export function OrderSummary({ order }: { order: OrderOut }) {
  const t = useTranslations("web.orders");
  const locale = useLocale();
  return (
    <dl className="grid grid-cols-2 gap-y-2 text-sm">
      <dt className="text-muted-foreground">{t("total")}</dt>
      <dd className="text-right font-semibold">
        {formatMoney(order.total_charged, order.currency, locale)}
      </dd>

      {order.payment_provider ? (
        <>
          <dt className="text-muted-foreground">{t("paidWith")}</dt>
          <dd className="flex justify-end">
            <PaymentProviderBadge provider={order.payment_provider} />
          </dd>
        </>
      ) : null}

      <dt className="text-muted-foreground">{t("createdAt")}</dt>
      <dd className="text-right">{fmtDate(order.created_at, locale)}</dd>

      {order.paid_at ? (
        <>
          <dt className="text-muted-foreground">{t("paidAt")}</dt>
          <dd className="text-right">{fmtDate(order.paid_at, locale)}</dd>
        </>
      ) : null}
      {order.delivered_at ? (
        <>
          <dt className="text-muted-foreground">{t("deliveredAt")}</dt>
          <dd className="text-right">{fmtDate(order.delivered_at, locale)}</dd>
        </>
      ) : null}
    </dl>
  );
}
