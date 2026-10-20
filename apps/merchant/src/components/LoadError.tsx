"use client";

import { RotateCw } from "lucide-react";
import { useTranslations } from "next-intl";

/**
 * A list that could not be read, said as such — with a retry.
 *
 * These screens used to show their empty state on any failure, so a timeout
 * read as «Заказов нет»: the one wrong answer a reseller reconciling money
 * must never get.
 */
export function LoadError({ onRetry }: { onRetry: () => void }) {
  const t = useTranslations("merchant.common");
  return (
    <div
      role="alert"
      className="border-border mt-8 flex flex-col items-center rounded-xl border px-6 py-10 text-center"
    >
      <p className="text-tx-mute text-sm">{t("loadError")}</p>
      <button
        type="button"
        onClick={onRetry}
        className="border-border rounded-btn mt-4 inline-flex items-center gap-2 border px-4 py-2 text-sm font-semibold"
      >
        <RotateCw aria-hidden size={14} />
        {t("errorRetry")}
      </button>
    </div>
  );
}
