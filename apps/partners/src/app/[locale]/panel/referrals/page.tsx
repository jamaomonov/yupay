"use client";

import { useLocale, useTranslations } from "next-intl";

import { formatDate, formatMoney, tidyPercent } from "@/lib/money";
import { useCommissions } from "@/lib/panel";

/** Commission states, and the key that names each. `void` reads as "reversed"
 *  rather than "cancelled": the order was fine, the refund took the money back. */
const STATUS_KEYS: Record<string, string> = {
  pending: "statusPending",
  available: "statusAvailable",
  paid: "statusPaid",
  void: "statusVoid",
};

export default function ReferralsPage() {
  const t = useTranslations("partners.panel");
  const { data, isSuccess } = useCommissions();
  const locale = useLocale();
  const rows = data?.items ?? [];

  if (isSuccess && rows.length === 0) {
    // In the same ruled band the table would occupy. A bare paragraph in the
    // top-left of an otherwise empty page reads as a page that failed to load.
    return (
      <div className="border-border border-y py-10">
        <p className="text-tx-mute max-w-prose text-[14px] leading-relaxed">
          {t("referralsEmpty")}
        </p>
      </div>
    );
  }

  const cell = "px-4 py-3 text-[13px]";
  // Money and percentages right-aligned with lining figures, so the digits
  // stack into a column a partner can compare down. Dates and statuses stay
  // left — they are read, not compared.
  const numeric = `${cell} text-right tabular-nums`;

  return (
    <div className="border-border overflow-x-auto border-y">
      <table className="w-full min-w-[640px] border-collapse">
        <thead>
          <tr className="border-border text-tx-mute border-b">
            <th className={`${cell} text-left font-medium`}>{t("colDate")}</th>
            <th className={`${numeric} font-medium`}>{t("colBase")}</th>
            <th className={`${numeric} font-medium`}>{t("colRate")}</th>
            <th className={`${numeric} font-medium`}>{t("colAmount")}</th>
            <th className={`${cell} text-left font-medium`}>{t("colStatus")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-border/60 border-b last:border-0">
              <td className={`${cell} text-tx-mute font-mono`}>
                {formatDate(row.created_at, locale)}
              </td>
              <td className={`${numeric} font-mono`}>
                {formatMoney(row.base_amount, row.currency, locale)}
              </td>
              <td className={`${numeric} text-tx-mute font-mono`}>{tidyPercent(row.percent)}%</td>
              <td className={`${numeric} text-primary font-mono font-semibold`}>
                {formatMoney(row.amount, row.currency, locale)}
              </td>
              <td className={`${cell} text-tx-mute`}>
                {t(STATUS_KEYS[row.status] ?? "statusPending")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
