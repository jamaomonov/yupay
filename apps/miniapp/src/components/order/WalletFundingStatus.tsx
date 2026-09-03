import { useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { useEffect } from "react";

import { TERMINAL_FAIL } from "./order-helpers";

import type { OrderOut } from "@/lib/orders";

import { useT } from "@/lib/i18n";
import { openExternalLink } from "@/lib/telegram";
import { formatBalance } from "@/lib/wallet";

/**
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function WalletFundingStatus({
  order,
  payUrl,
  onWallet,
  onHome,
}: {
  order: OrderOut;
  payUrl: string | null;
  onWallet: () => void;
  onHome: () => void;
}) {
  const { t } = useT();
  const qc = useQueryClient();
  const charged = Number.parseFloat(order.total_charged) || 0;
  const amountLabel = formatBalance(charged, order.currency);
  const delivered = order.status === "delivered";
  const failed = TERMINAL_FAIL.includes(order.status);

  useEffect(() => {
    if (delivered) void qc.invalidateQueries({ queryKey: ["wallet"] });
  }, [delivered, qc]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className="space-y-4 px-4 pb-8 pt-6"
    >
      <div className="flex flex-col items-center text-center">
        {delivered ? (
          <CheckCircle2 size={48} className="text-[hsl(var(--primary))]" />
        ) : failed ? (
          <XCircle size={48} className="text-red-400" />
        ) : (
          <Loader2 size={48} className="animate-spin text-white/50" />
        )}
        <h1 className="mt-4 text-xl font-bold text-white">
          {delivered
            ? t("walletTopUp.credited")
            : failed
              ? t("walletTopUp.failed")
              : t("walletTopUp.waiting")}
        </h1>
        <p className="mt-2 text-2xl font-bold tabular-nums text-white">{amountLabel}</p>
        <p className="mt-1 text-sm text-white/50">{t("walletTopUp.disclaimerAfter")}</p>
      </div>
      {order.status === "pending_payment" && payUrl ? (
        <button
          type="button"
          onClick={() => {
            openExternalLink(payUrl);
          }}
          className="w-full rounded-2xl py-3.5 text-sm font-bold"
          style={{ background: "hsl(var(--primary))", color: "#000" }}
        >
          {t("walletTopUp.payAgain")}
        </button>
      ) : null}
      <button
        type="button"
        onClick={delivered ? onWallet : onHome}
        className="w-full rounded-2xl py-3 text-sm font-semibold text-white"
        style={{ background: "hsl(var(--surface-1))", border: "1px solid hsl(var(--border))" }}
      >
        {delivered ? t("walletTopUp.toWallet") : t("common.toHome")}
      </button>
    </motion.div>
  );
}
