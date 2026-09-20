import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useId, useRef, useState } from "react";

import {
  T,
  debitDeposit,
  fill,
  formatUsd,
  parseUsdAmount,
  sameAmount,
  subtractUsd,
  toCents,
  type DepositDebitOut,
} from "./api";

import type { ApiError } from "@/lib/api";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { MoneyInput } from "@/components/MoneyInput";
import { useToast } from "@/components/Toast";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

interface Props {
  merchantId: string;
  merchantTitle: string;
  /** The live balance, for the overdraw check and the «whole balance» button. */
  balance: string;
  /** Called with the authoritative balance the API returned. */
  onBalance: (balance: string) => void;
}

/**
 * Taking money back off a merchant's prepaid deposit.
 *
 * **A separate card rather than a negative amount in «Пополнить депозит».**
 * An operator tried exactly that — typing `−1` into the credit form — and got
 * "сумма должна быть положительной", which is the form working as designed and
 * still a dead end. Making the credit field accept a minus would have been the
 * smaller diff and the worse control:
 *
 * - the two endpoints have different contracts — a debit REQUIRES a reason and
 *   accepts no `order_id`, because attributing it to an order would publish
 *   money on that order's `refunded_usd` the merchant never got back;
 * - a minus sign is one keystroke, and the button under it says «Зачислить».
 *   A form that adds or removes money depending on a character that renders
 *   four pixels wide is a money mistake waiting for a tired evening.
 *
 * The confirm dialog names the resulting balance, not just the amount, because
 * "how much will be left" is the number the operator is actually deciding on.
 */
export function DepositDebitCard({ merchantId, merchantTitle, balance, onBalance }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const amountFieldId = useId();
  const reasonFieldId = useId();

  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  const [pending, setPending] = useState<{ amount: string } | null>(null);
  const keyRef = useRef("");
  // `isPending` re-renders one tick after `mutate`; a same-tick double-click
  // would fire twice. The ref flips synchronously. (Same reasoning as the
  // credit form beside it — and here a double-fire is two debits.)
  const inFlightRef = useRef(false);

  const mutation = useMutation<DepositDebitOut, ApiError, { amount: string; reason: string }>({
    mutationFn: (body) => debitDeposit(merchantId, body, keyRef.current),
    onSettled: () => {
      inFlightRef.current = false;
    },
    onSuccess: (data, vars) => {
      setPending(null);
      // The ledger replays by key WITHOUT comparing parameters, so a reused
      // key returns the original transaction and books nothing. Saying so is
      // the only way the operator learns their amount was not applied.
      if (!sameAmount(data.amount, vars.amount)) {
        toast.error(
          fill(T.debit.replayMismatch, {
            booked: formatUsd(data.amount),
            typed: formatUsd(vars.amount),
          }),
        );
      } else {
        toast.success(
          fill(T.debit.success, {
            amount: formatUsd(data.amount),
            balance: formatUsd(data.balance),
          }),
        );
        setAmount("");
        setReason("");
      }
      onBalance(data.balance);
      void qc.invalidateQueries({ queryKey: qk.merchantTxns(merchantId) });
    },
    onError: (err) => {
      // The dialog stays open: a retry reuses the same key, which is the
      // whole point of minting it before the confirm.
      toast.error(fill(T.debit.error, { message: extractApiMessage(err) }));
    },
  });

  const submit = () => {
    const parsed = parseUsdAmount(amount);
    if (parsed === null) {
      toast.error(T.debit.amountInvalid);
      return;
    }
    if (!reason.trim()) {
      toast.error(T.debit.reasonRequired);
      return;
    }
    // Checked here as well as on the server, which answers
    // `409 insufficient_deposit`. Client-side it is the difference between a
    // refused request and a dialog that never opens on an amount that cannot
    // work — and the dialog is where the operator is about to say "yes".
    if (toCents(parsed) > toCents(balance)) {
      toast.error(fill(T.debit.overdraw, { balance: formatUsd(balance) }));
      return;
    }
    keyRef.current = `merchant-debit-${crypto.randomUUID()}`;
    setPending({ amount: parsed });
  };

  const confirm = () => {
    if (pending === null || inFlightRef.current) return;
    inFlightRef.current = true;
    mutation.mutate({ amount: pending.amount, reason: reason.trim() });
  };

  return (
    <section className="mb-6 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h2 className="mb-1 text-sm font-semibold">{T.debit.title}</h2>
      <p className="mb-1 text-xs text-[var(--text-secondary)]">{T.debit.hint}</p>
      <p className="mb-3 text-xs text-[var(--text-secondary)]">{T.debit.noWebhook}</p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div>
          <label htmlFor={amountFieldId} className="text-xs uppercase text-[var(--text-secondary)]">
            {T.debit.amountLabel}
          </label>
          <MoneyInput
            id={amountFieldId}
            value={amount}
            onChange={setAmount}
            placeholder={T.debit.amountPlaceholder}
            className="mt-1 font-mono"
          />
        </div>
        <div className="md:col-span-2">
          <label htmlFor={reasonFieldId} className="text-xs uppercase text-[var(--text-secondary)]">
            {T.debit.reasonLabel} <span className="normal-case">{T.debit.reasonHint}</span>
          </label>
          <Input
            id={reasonFieldId}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            placeholder={T.debit.reasonPlaceholder}
            className="mt-1"
          />
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button variant="danger" onClick={submit} disabled={mutation.isPending}>
          {mutation.isPending ? T.debit.submitBusy : T.debit.submit}
        </Button>
        {/* Zeroing a balance is the common case — a test merchant being
            cleaned up — and typing it by hand is how an operator debits
            $3.39 out of $3.93. */}
        <Button
          variant="ghost"
          onClick={() => {
            setAmount(balance);
          }}
          disabled={mutation.isPending || toCents(balance) <= 0}
        >
          {T.debit.wholeBalance}
        </Button>
      </div>

      {pending !== null && (
        <ConfirmDialog
          title={T.debit.confirmTitle}
          tone="danger"
          confirmLabel={T.debit.confirm}
          busy={mutation.isPending}
          onCancel={() => {
            setPending(null);
          }}
          onConfirm={confirm}
        >
          <p>
            {fill(T.debit.confirmBody, {
              title: merchantTitle,
              amount: formatUsd(pending.amount),
              // The number the operator is actually deciding on.
              rest: formatUsd(subtractUsd(balance, pending.amount)),
            })}
          </p>
        </ConfirmDialog>
      )}
    </section>
  );
}
