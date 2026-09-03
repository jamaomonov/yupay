import { providerIcon, providerLabel } from "./order-helpers";

import type { OrderOut } from "@/lib/orders";

import { useT } from "@/lib/i18n";
import { getActiveLocale } from "@/lib/i18n/core";

function Row({ label, value, icon }: { label: string; value: string; icon?: string | null }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-white/45">{label}</span>
      <span className="flex items-center gap-1.5 font-medium text-white">
        {icon && (
          <span className="flex h-4 w-4 items-center justify-center overflow-hidden rounded-sm bg-white">
            <img src={icon} alt="" className="h-full w-full object-contain" />
          </span>
        )}
        {value}
      </span>
    </div>
  );
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString(getActiveLocale(), {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/**
 * Order summary footer — amount, payment provider, timestamps.
 *
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function Summary({ order }: { order: OrderOut }) {
  const { t } = useT();
  const providerText = providerLabel(order.payment_provider);
  const providerIconSrc = providerIcon(order.payment_provider);
  return (
    <div className="px-4">
      <div
        className="space-y-1.5 rounded-2xl p-4 text-xs"
        style={{
          background: "hsl(var(--surface-1))",
          border: "1px solid hsl(var(--border))",
        }}
      >
        <Row
          label={t("success.amount")}
          value={`${Number.parseFloat(order.total_charged).toLocaleString(getActiveLocale(), { maximumFractionDigits: 2 })} ${order.currency}`}
        />
        {providerText && (
          <Row label={t("success.paidWith")} value={providerText} icon={providerIconSrc} />
        )}
        <Row label={t("success.createdAt")} value={fmtDate(order.created_at)} />
        {order.paid_at && <Row label={t("success.paidAt")} value={fmtDate(order.paid_at)} />}
        {order.delivered_at && (
          <Row label={t("success.deliveredAt")} value={fmtDate(order.delivered_at)} />
        )}
      </div>
    </div>
  );
}
