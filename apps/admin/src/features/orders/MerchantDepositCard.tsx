/**
 * A merchant order's money, and the one button that moves it (M3c Task 4).
 *
 * A `/merchant/v1` order has no `Payment` row at all — its money is a charge on
 * the reseller's USD deposit ledger — so the payments card beside this one
 * correctly reads «Платежи (0)» and says nothing else. An operator looking at a
 * failed B2B order therefore had no money on the page and no refund
 * affordance: the settlement lives on the *merchant's* page, and they were
 * standing somewhere else.
 *
 * This card is the two numbers and, when the order can be settled, the button.
 * It is deliberately **not** a second money path: it posts the same attributed
 * deposit credit support has always posted (`POST /admin/merchants/{id}/
 * deposit-credits` with `order_id`), for the amount the ledger says the order
 * charged, with a fresh `Idempotency-Key` per attempt.
 *
 * ## It is not an auto-refund and must not read as one
 *
 * The owner's standing rule is that after a human action a human decides. The
 * confirmation names the merchant, the amount and the order before anything
 * posts, and says what else the press does: the order closes, and once the
 * whole charge is back neither Retry nor manual delivery will touch it again.
 *
 * ## Double settlement
 *
 * Impossible from here twice over. `merchantSettlement` hides the button the
 * moment anything has come back, and the server refuses an over-settlement
 * with `order_already_settled` — which this renders as a sentence an operator
 * can act on rather than as a raw 409.
 *
 * ## When it is offered at all
 *
 * `merchantSettlement` decides, and its docstring carries the reasons. The one
 * worth knowing here is that the button waits for a **terminally stopped**
 * delivery rather than for any unsettled merchant order: settling a live one
 * returns the money and stops nothing, so the drain can still hand the reseller
 * the goods. That gap is the API's and older than this card; the card simply
 * declines to be a one-click way into it.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button } from "@yupay/ui";
import { Coins } from "lucide-react";
import { useRef, useState } from "react";

import { merchantSettlement, settlementBlock } from "./settlement";
import type { OrderAdminOut } from "./types";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { fill, formatUsd } from "@/features/merchants/api";
import { type ApiError, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

import adminRu from "@yupay/i18n/locales/ru/admin.json";

const T = adminRu.orders.settle;

/** RFC 7807 `code` for a settlement that would take an order past its charge. */
const ALREADY_SETTLED = "order_already_settled";

function isAlreadySettled(err: unknown): boolean {
  // The code, not the message: `detail` is prose and gets rewritten, while the
  // code is the published half of the contract (`deposit.CODE_ORDER_ALREADY_SETTLED`).
  const body = (err as { body?: { code?: unknown } } | null)?.body;
  return body?.code === ALREADY_SETTLED;
}

export function MerchantDepositCard({ order }: { order: OrderAdminOut }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [confirming, setConfirming] = useState(false);
  const [refused, setRefused] = useState(false);
  // One key per **attempt**, minted when the confirmation opens and held in a
  // ref, exactly as the merchant page's credit form does. Minting it inside
  // `mutationFn` would give a second call a second key, and two keys are two
  // credits: the ledger replays by key, so only a stable one makes a retry a
  // replay rather than a fresh posting.
  const keyRef = useRef("");
  // `isPending` — and therefore `ConfirmDialog`'s `busy` — only goes true one
  // render after `mutate`, so two clicks in the same tick both get through a
  // still-enabled button. This ref flips synchronously. Without it the two
  // requests race `_refuse_over_settlement`'s pre-read, both see nothing
  // returned, and the deposit is credited twice for one order — which is the
  // defect that cap exists to prevent, defeated by a double-click.
  const inFlightRef = useRef(false);

  const settlement = merchantSettlement(order);
  const blocked = settlementBlock(order);

  const settle = useMutation<unknown, ApiError, { merchantId: string; amount: string }>({
    mutationFn: ({ merchantId, amount }) =>
      apiPost(
        `/api/v1/admin/merchants/${merchantId}/deposit-credits`,
        {
          amount,
          order_id: order.id,
          note: fill(T.note, { order: order.id }),
        },
        // The attempt's own key — see `keyRef`. A retry of this attempt replays
        // the ledger transaction instead of crediting a second time, which is
        // the whole reason the header is required.
        { "Idempotency-Key": keyRef.current },
      ),
    onSettled: () => {
      inFlightRef.current = false;
    },
    onSuccess: (_data, vars) => {
      setConfirming(false);
      setRefused(false);
      toast.success(fill(T.success, { amount: formatUsd(vars.amount) }));
      void qc.invalidateQueries({ queryKey: qk.order(order.id) });
      void qc.invalidateQueries({ queryKey: ["admin", "orders"] });
      // Through the helper, not a hand-written tuple (`queryKeys.ts`'s own
      // rule). It prefix-matches the merchant's ledger listing too, which is
      // right: this moved the balance *and* added a row to it.
      void qc.invalidateQueries({ queryKey: qk.merchants() });
    },
    onError: (err) => {
      if (isAlreadySettled(err)) {
        // A decision, not a failure: the money is already back, so there is
        // nothing to retry. Close the dialog and say it in a sentence — the
        // operator's next move is to read the numbers above and the merchant's
        // ledger, and a raw 409 says neither.
        setConfirming(false);
        setRefused(true);
        return;
      }
      // Anything else may be transient (a timeout, a dropped connection), and
      // the dialog **stays open** so the operator can press again. That press
      // reuses `keyRef`, so it replays the ledger transaction if the first
      // request actually landed — the case where closing the dialog and
      // re-opening it would mint a second key and credit the order twice.
      toast.error(fill(T.error, { message: extractApiMessage(err) }));
    },
  });

  if (order.merchant_id === null) return null;

  return (
    <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]">
      <header className="flex items-center gap-2 border-b px-4 py-3">
        <Coins className="size-4 text-[var(--text-secondary)]" />
        <h2 className="text-sm font-semibold">{T.title}</h2>
      </header>
      <div className="space-y-3 p-4 text-sm">
        <dl className="space-y-1">
          <div className="flex items-baseline justify-between">
            <dt className="text-[var(--text-secondary)]">{T.chargedLabel}</dt>
            <dd className="font-mono font-medium">
              {order.deposit_charged_usd === null ? "—" : formatUsd(order.deposit_charged_usd)}
            </dd>
          </div>
          <div className="flex items-baseline justify-between">
            <dt className="text-[var(--text-secondary)]">{T.returnedLabel}</dt>
            <dd className="font-mono font-medium">{formatUsd(order.deposit_returned_usd)}</dd>
          </div>
        </dl>

        {refused && (
          <p
            role="alert"
            className="rounded-md border border-[var(--danger)] bg-[var(--danger-soft)] p-2 text-xs font-medium text-[var(--danger-fg)]"
          >
            {T.alreadySettled}
          </p>
        )}

        {settlement !== null ? (
          <Button
            variant="danger"
            onClick={() => {
              setRefused(false);
              // Minted per opened dialog, not per press of the dialog's own
              // button: a retry after a timeout must replay, a fresh decision
              // must not.
              keyRef.current = `admin-settle-${crypto.randomUUID()}`;
              setConfirming(true);
            }}
            disabled={settle.isPending}
          >
            {settle.isPending ? T.buttonBusy : T.button}
          </Button>
        ) : (
          blocked !== null && (
            <p className="text-xs text-[var(--text-secondary)]">{T.blocked[blocked]}</p>
          )
        )}
      </div>

      {confirming && settlement !== null && (
        <ConfirmDialog
          title={T.confirmTitle}
          tone="danger"
          confirmLabel={T.confirm}
          busy={settle.isPending}
          onCancel={() => {
            setConfirming(false);
          }}
          onConfirm={() => {
            if (inFlightRef.current) return;
            inFlightRef.current = true;
            settle.mutate({ merchantId: settlement.merchantId, amount: settlement.amount });
          }}
        >
          <p>
            {fill(T.confirmBody, {
              merchant: order.merchant_title ?? settlement.merchantId,
              amount: formatUsd(settlement.amount),
              order: order.id,
            })}
          </p>
          <p className="mt-2">{T.confirmClosing}</p>
        </ConfirmDialog>
      )}
    </div>
  );
}
