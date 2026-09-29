/**
 * The two things an operator can do to a trade from its details: give the money back to
 * the buyer's YuPay balance, or re-run a failed purchase. The API says which apply
 * (`can_refund`, `can_retry`); both ask first — a refund tells the customer, and a retry of
 * a buy Waxpeer did make would buy the skin twice.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";

import { fill, refundTrade, retryTask, T, usd, type AdminSkinTradeOut } from "./api";

import { ApiError, formatApiError } from "@/lib/api";

const D = T.trades.drawer;

function errorText(err: unknown): string {
  return fill(D.actionError, {
    error: err instanceof ApiError ? formatApiError(err) : String(err),
  });
}

export function TradeActions({ trade, onDone }: { trade: AdminSkinTradeOut; onDone: () => void }) {
  const qc = useQueryClient();
  const settle = {
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["admin", "skins"] });
      onDone();
    },
  };
  const refund = useMutation({ mutationFn: () => refundTrade(trade.id), ...settle });
  const retry = useMutation({
    mutationFn: () => retryTask(trade.task_id ?? ""),
    ...settle,
  });

  if (trade.refunded_to) {
    return (
      <p className="rounded-md bg-[var(--bg-muted)] p-3 text-sm">
        {trade.refunded_to === "wallet" ? D.refundedWallet : D.refundedCard}
      </p>
    );
  }
  if (!trade.can_refund && !(trade.can_retry && trade.task_id)) return null;
  const busy = refund.isPending || retry.isPending;
  const failed = refund.error ?? retry.error;

  return (
    <section className="space-y-2 rounded-md border border-[var(--border-default)] p-3">
      <h3 className="text-sm font-semibold">{D.actionsTitle}</h3>
      <div className="flex flex-wrap gap-2">
        {trade.can_refund && (
          <Button
            disabled={busy}
            onClick={() => {
              if (window.confirm(fill(D.refundConfirm, { amount: usd(trade.sold_usd) }))) {
                refund.mutate();
              }
            }}
          >
            {D.refund}
          </Button>
        )}
        {trade.can_retry && trade.task_id && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => {
              if (window.confirm(fill(D.retryConfirm, { project: trade.project_id }))) {
                retry.mutate();
              }
            }}
          >
            {D.retry}
          </Button>
        )}
      </div>
      {failed && (
        <p role="alert" className="text-sm text-[var(--danger)]">
          {errorText(failed)}
        </p>
      )}
    </section>
  );
}
