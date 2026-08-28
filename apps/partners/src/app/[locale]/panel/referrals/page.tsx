"use client";

import { useTranslations } from "next-intl";

import { formatMoney } from "@/lib/money";
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
  const rows = data?.items ?? [];

  if (isSuccess && rows.length === 0) {
    return <p className="text-tx-mute text-[14px] leading-relaxed">{t("referralsEmpty")}</p>;
  }

  const cell = "px-4 py-3 text-[13px]";

  return (
    <div className="border-border bg-card overflow-x-auto rounded-xl border">
      <table className="w-full min-w-[640px] border-collapse">
        <thead>
          <tr className="border-border text-tx-mute border-b text-left">
            <th className={`${cell} font-medium`}>{t("colDate")}</th>
            <th className={`${cell} font-medium`}>{t("colBase")}</th>
            <th className={`${cell} font-medium`}>{t("colRate")}</th>
            <th className={`${cell} font-medium`}>{t("colAmount")}</th>
            <th className={`${cell} font-medium`}>{t("colStatus")}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id} className="border-border/60 border-b last:border-0">
              <td className={`${cell} text-tx-mute font-mono`}>
                {new Date(row.created_at).toLocaleDateString("ru-RU")}
              </td>
              <td className={`${cell} font-mono`}>{formatMoney(row.base_amount, row.currency)}</td>
              <td className={`${cell} text-tx-mute font-mono`}>{row.percent}%</td>
              <td className={`${cell} text-primary font-mono font-semibold`}>
                {formatMoney(row.amount, row.currency)}
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
