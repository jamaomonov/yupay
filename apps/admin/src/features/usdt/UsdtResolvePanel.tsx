/**
 * Resolve an unmatched USDT transfer: credit it to a reseller, or close it
 * without crediting anyone. Both go through a confirm dialog that shows the
 * concrete numbers; the credit shows the amount rounded DOWN to cents, which
 * is what the API books.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { useRef, useState } from "react";

import {
  creditIncoming,
  dismissIncoming,
  fill,
  floorToCents,
  formatUsdt,
  T,
  usdtErrorMessage,
  type UsdtIncoming,
} from "./api";

import type { ApiError } from "@/lib/api";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { fetchMerchants } from "@/features/merchants/api";
import { qk } from "@/lib/queryKeys";

export type ResolveAction = "credit" | "dismiss";

const R = T.resolve;
const LABEL = "mb-1 block text-xs text-[var(--text-secondary)]";

interface Props {
  row: UsdtIncoming;
  action: ResolveAction;
  onClose: () => void;
}

export function UsdtResolvePanel({ row, action, onClose }: Props) {
  const qc = useQueryClient();
  const toast = useToast();
  const [merchantId, setMerchantId] = useState("");
  const [note, setNote] = useState("");
  const [confirming, setConfirming] = useState(false);
  const idemKey = useRef<string | null>(null);
  const isCredit = action === "credit";

  const merchants = useQuery({
    queryKey: qk.merchants(),
    queryFn: fetchMerchants,
    enabled: isCredit,
  });
  const merchant = merchants.data?.items.find((m) => m.id === merchantId) ?? null;
  const credited = floorToCents(row.amount_usdt);
  const usdt = formatUsdt(row.amount_usdt);
  const trimmedNote = note.trim();

  const resolve = useMutation<UsdtIncoming, ApiError>({
    mutationFn: () => {
      idemKey.current ??= crypto.randomUUID();
      if (isCredit) {
        const body = trimmedNote
          ? { merchant_id: merchantId, note: trimmedNote }
          : { merchant_id: merchantId };
        return creditIncoming(row.id, body, idemKey.current);
      }
      return dismissIncoming(row.id, trimmedNote, idemKey.current);
    },
    onSuccess: () => {
      idemKey.current = null;
      void qc.invalidateQueries({ queryKey: qk.usdtIncomingAll() });
      toast.success(isCredit ? fill(R.credited, { amount: credited }) : R.dismissed);
      onClose();
    },
    onError: () => {
      setConfirming(false);
    },
  });

  const ready = isCredit ? merchant !== null : trimmedNote !== "";

  return (
    <aside
      className="mb-4 max-w-xl rounded-lg border bg-[var(--bg-surface)] p-4"
      aria-label={fill(isCredit ? R.creditTitle : R.dismissTitle, { amount: usdt })}
      onChange={() => {
        idemKey.current = null;
      }}
    >
      <h3 className="mb-3 font-medium">
        {fill(isCredit ? R.creditTitle : R.dismissTitle, { amount: usdt })}
      </h3>
      {isCredit ? (
        <label className="mb-3 block text-sm">
          <span className={LABEL}>{R.merchant}</span>
          <select
            className="h-9 w-full rounded-md border bg-[var(--bg-surface)] px-2 text-sm"
            value={merchantId}
            disabled={merchants.isLoading}
            onChange={(e) => {
              setMerchantId(e.target.value);
            }}
          >
            <option value="">{R.pickMerchant}</option>
            {merchants.data?.items.map((m) => (
              <option key={m.id} value={m.id}>
                {m.title}
              </option>
            ))}
          </select>
          {merchants.isError ? (
            <span role="alert" className="mt-1 block text-xs text-[var(--danger)]">
              {R.merchantsError}
            </span>
          ) : null}
        </label>
      ) : null}
      <label className="mb-3 block text-sm">
        <span className={LABEL}>{isCredit ? R.noteOptional : R.note}</span>
        <Input
          maxLength={256}
          value={note}
          onChange={(e) => {
            setNote(e.target.value);
          }}
        />
        {!isCredit && trimmedNote === "" ? (
          <span className="mt-1 block text-xs text-[var(--text-secondary)]">{R.noteRequired}</span>
        ) : null}
      </label>
      {resolve.isError ? (
        <p role="alert" className="mb-2 text-sm text-[var(--danger)]">
          {usdtErrorMessage(resolve.error)}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button
          variant={isCredit ? "primary" : "danger"}
          disabled={!ready || resolve.isPending}
          onClick={() => {
            setConfirming(true);
          }}
        >
          {isCredit ? T.journal.credit : T.journal.dismiss}
        </Button>
        <Button variant="ghost" disabled={resolve.isPending} onClick={onClose}>
          {R.cancel}
        </Button>
      </div>
      {confirming ? (
        <ConfirmDialog
          title={isCredit ? R.confirmCreditTitle : R.confirmDismissTitle}
          confirmLabel={isCredit ? fill(R.confirmCredit, { amount: credited }) : R.confirmDismiss}
          cancelLabel={R.cancel}
          tone="danger"
          busy={resolve.isPending}
          onConfirm={() => {
            resolve.mutate();
          }}
          onCancel={() => {
            setConfirming(false);
          }}
        >
          <p className="text-sm">
            {isCredit
              ? fill(R.confirmCreditBody, { amount: credited, merchant: merchant?.title ?? "" })
              : fill(R.confirmDismissBody, { amount: usdt })}
          </p>
        </ConfirmDialog>
      ) : null}
    </aside>
  );
}
