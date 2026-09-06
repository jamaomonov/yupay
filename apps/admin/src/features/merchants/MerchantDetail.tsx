/**
 * Merchant detail (`/merchants/:id`) — freeze toggle, deposit credit, ledger.
 *
 * The deposit-credit form is the UI half of a money-safety mechanism: the
 * endpoint replays by idempotency key WITHOUT comparing parameters, and its
 * response carries the amount the ledger ACTUALLY booked. When that differs
 * from what the operator typed (a reused key with an amended amount), the
 * form shows a prominent warning instead of a success toast — the mismatch
 * must never be silent. One key is minted per logical credit attempt
 * (stable across retries of that attempt), and an in-flight ref blocks
 * double-submit.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { Snowflake, Sun } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import {
  T,
  creditDeposit,
  fetchMerchants,
  fetchMerchantTxns,
  fill,
  formatUsd,
  parseUsdAmount,
  sameAmount,
  setMerchantFrozen,
  type DepositCreditOut,
  type MerchantListOut,
  type MerchantOut,
  type MerchantTxnListOut,
  type MerchantTxnOut,
} from "./api";

import type { ApiError } from "@/lib/api";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { DataTable, type Column } from "@/components/DataTable";
import { MoneyInput } from "@/components/MoneyInput";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { Spinner } from "@/components/States";
import { StatusChip } from "@/components/StatusChip";
import { useToast } from "@/components/Toast";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";

export function MerchantDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const amountFieldId = useId();
  const noteFieldId = useId();

  // There is no single-merchant GET — the list is one grouped query and the
  // detail reuses its cache entry.
  const listQuery = useQuery<MerchantListOut>({
    queryKey: qk.merchants(),
    queryFn: fetchMerchants,
  });
  const merchant = listQuery.data?.items.find((m) => m.id === id) ?? null;

  const txnsQuery = useQuery<MerchantTxnListOut>({
    queryKey: qk.merchantTxns(id),
    queryFn: () => fetchMerchantTxns(id),
    enabled: Boolean(id),
  });

  // ----- freeze / unfreeze -----
  const [confirmFreeze, setConfirmFreeze] = useState<boolean | null>(null);
  const freezeKeyRef = useRef("");

  const patchList = (updated: MerchantOut) => {
    qc.setQueryData<MerchantListOut>(qk.merchants(), (prev) =>
      prev ? { ...prev, items: prev.items.map((m) => (m.id === updated.id ? updated : m)) } : prev,
    );
  };

  const freezeMutation = useMutation<MerchantOut, ApiError, boolean>({
    mutationFn: (frozen) => setMerchantFrozen(id, frozen, freezeKeyRef.current),
    onSuccess: (updated, frozen) => {
      setConfirmFreeze(null);
      patchList(updated);
      toast.success(frozen ? T.detail.frozenToast : T.detail.unfrozenToast);
    },
    onError: (err) => {
      toast.error(fill(T.detail.statusError, { message: extractApiMessage(err) }));
    },
  });

  // ----- deposit credit -----
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  /** Canonical amount awaiting confirmation; `null` = no dialog. */
  const [pendingCredit, setPendingCredit] = useState<string | null>(null);
  const [lastCredit, setLastCredit] = useState<DepositCreditOut | null>(null);
  const [mismatch, setMismatch] = useState<{ booked: string; typed: string } | null>(null);
  const creditKeyRef = useRef("");
  // `isPending` re-renders one tick after `mutate` — a same-tick double-click
  // would fire twice. The ref flips synchronously.
  const creditInFlightRef = useRef(false);

  const creditMutation = useMutation<
    DepositCreditOut,
    ApiError,
    { amount: string; note: string | null }
  >({
    mutationFn: (body) => creditDeposit(id, body, creditKeyRef.current),
    onSettled: () => {
      creditInFlightRef.current = false;
    },
    onSuccess: (data, vars) => {
      setPendingCredit(null);
      setLastCredit(data);
      if (!sameAmount(data.amount, vars.amount)) {
        // Replayed key with an amended amount: the ledger booked the ORIGINAL
        // transaction and ignored what was typed. Loud banner, no success toast.
        setMismatch({ booked: data.amount, typed: vars.amount });
      } else {
        setMismatch(null);
        toast.success(
          fill(T.credit.success, {
            amount: formatUsd(data.amount),
            balance: formatUsd(data.balance),
          }),
        );
        setAmount("");
        setNote("");
      }
      // The response balance is authoritative either way.
      if (merchant) patchList({ ...merchant, deposit_balance: data.balance });
      void qc.invalidateQueries({ queryKey: qk.merchantTxns(id) });
    },
    onError: (err) => {
      // The confirm dialog stays open — a retry reuses the same key.
      toast.error(fill(T.credit.error, { message: extractApiMessage(err) }));
    },
  });

  const submitCredit = () => {
    const parsed = parseUsdAmount(amount);
    if (parsed === null) {
      toast.error(T.credit.amountInvalid);
      return;
    }
    // One key per logical attempt (minted here, not in the confirm click):
    // retries of this attempt replay it, the next submit mints a fresh one.
    creditKeyRef.current = `merchant-topup-${crypto.randomUUID()}`;
    setMismatch(null);
    setPendingCredit(parsed);
  };

  const confirmCredit = () => {
    if (pendingCredit === null || creditInFlightRef.current) return;
    creditInFlightRef.current = true;
    creditMutation.mutate({ amount: pendingCredit, note: note.trim() ? note.trim() : null });
  };

  const isFrozen = merchant?.status === "frozen";

  const txnColumns: Column<MerchantTxnOut>[] = [
    {
      key: "created",
      header: T.ledger.columns.created,
      render: (t) => (
        <span className="text-[var(--text-secondary)]">
          {new Date(t.created_at).toLocaleString("ru")}
        </span>
      ),
      className: "w-40",
    },
    {
      key: "kind",
      header: T.ledger.columns.kind,
      render: (t) => <StatusChip domain="walletTxKind" value={t.kind} />,
    },
    {
      key: "amount",
      header: T.ledger.columns.amount,
      render: (t) => (
        <span
          className={`font-medium ${
            t.amount.startsWith("-") ? "text-[var(--danger-fg)]" : "text-[var(--success-fg)]"
          }`}
        >
          {t.amount.startsWith("-") ? "" : "+"}
          {formatUsd(t.amount)}
        </span>
      ),
      className: "w-32 text-right",
    },
    {
      key: "note",
      header: T.ledger.columns.note,
      render: (t) =>
        t.note ? <span>«{t.note}»</span> : <span className="text-[var(--text-secondary)]">—</span>,
    },
    {
      key: "actor",
      header: T.ledger.columns.actor,
      render: (t) =>
        t.actor ? (
          <span className="font-mono text-xs text-[var(--text-secondary)]">{t.actor}</span>
        ) : (
          <span className="text-[var(--text-secondary)]">—</span>
        ),
      className: "w-44",
    },
  ];

  if (listQuery.isLoading) return <Spinner label={T.detail.loading} />;
  if (listQuery.isError) return <p className="text-sm text-[var(--danger)]">{T.list.loadError}</p>;
  if (!merchant) {
    // A stale cache can land here mid-refetch — e.g. right after a create,
    // when navigation beats the invalidated list. Keep the spinner up until
    // the in-flight fetch settles; only a settled list may say "not found".
    if (listQuery.isFetching) return <Spinner label={T.detail.loading} />;
    return <p className="text-sm text-[var(--text-secondary)]">{T.detail.notFound}</p>;
  }

  return (
    <div>
      <PageHeader
        title={merchant.title}
        breadcrumbs={[{ label: T.list.title, to: "/merchants" }, { label: merchant.title }]}
        actions={
          <Button
            variant={isFrozen ? "primary" : "danger"}
            onClick={() => {
              freezeKeyRef.current = `merchant-status-${crypto.randomUUID()}`;
              setConfirmFreeze(!isFrozen);
            }}
          >
            {isFrozen ? <Sun className="size-4" /> : <Snowflake className="size-4" />}
            {isFrozen ? T.detail.unfreeze : T.detail.freeze}
          </Button>
        }
      />

      <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3">
        <StatCard label={T.detail.balanceLabel} value={formatUsd(merchant.deposit_balance)} mono />
        <div className="rounded-lg border bg-[var(--bg-surface)] p-3 shadow-[var(--shadow-sm)]">
          <p className="text-xs uppercase text-[var(--text-secondary)]">{T.detail.statusLabel}</p>
          <div className="mt-1">
            <StatusChip domain="merchantStatus" value={merchant.status} />
          </div>
        </div>
        <StatCard
          label={T.detail.createdLabel}
          value={new Date(merchant.created_at).toLocaleDateString("ru")}
        />
      </section>

      {mismatch && (
        <div
          role="alert"
          className="mb-5 rounded-lg border border-[var(--danger)] bg-[var(--danger-soft)] p-4 text-sm font-medium text-[var(--danger-fg)]"
        >
          {fill(T.credit.replayMismatch, {
            booked: formatUsd(mismatch.booked),
            typed: formatUsd(mismatch.typed),
          })}
        </div>
      )}

      <section className="mb-6 rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
        <h2 className="mb-1 text-sm font-semibold">{T.credit.title}</h2>
        <p className="mb-3 text-xs text-[var(--text-secondary)]">{T.credit.hint}</p>
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <div>
            <label
              htmlFor={amountFieldId}
              className="text-xs uppercase text-[var(--text-secondary)]"
            >
              {T.credit.amountLabel}
            </label>
            <MoneyInput
              id={amountFieldId}
              value={amount}
              onChange={setAmount}
              placeholder={T.credit.amountPlaceholder}
              className="mt-1 font-mono"
            />
          </div>
          <div className="md:col-span-2">
            <label htmlFor={noteFieldId} className="text-xs uppercase text-[var(--text-secondary)]">
              {T.credit.noteLabel} <span className="normal-case">{T.credit.noteHint}</span>
            </label>
            <Input
              id={noteFieldId}
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
              }}
              placeholder={T.credit.notePlaceholder}
              className="mt-1"
            />
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <Button onClick={submitCredit} disabled={creditMutation.isPending}>
            {creditMutation.isPending ? T.credit.submitBusy : T.credit.submit}
          </Button>
          {lastCredit && (
            <p className="text-sm text-[var(--text-secondary)]">
              {fill(T.credit.resultBalance, { balance: formatUsd(lastCredit.balance) })}
            </p>
          )}
        </div>
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase text-[var(--text-secondary)]">
          {T.ledger.title}
        </h2>
        {txnsQuery.isError && <p className="text-sm text-[var(--danger)]">{T.ledger.loadError}</p>}
        <DataTable
          rows={txnsQuery.data?.items ?? []}
          columns={txnColumns}
          rowKey={(t) => t.transaction_id}
          loading={txnsQuery.isLoading}
          empty={T.ledger.empty}
          ariaLabel={T.ledger.title}
          sortable={false}
        />
      </section>

      {confirmFreeze !== null && (
        <ConfirmDialog
          title={confirmFreeze ? T.detail.freezeConfirmTitle : T.detail.unfreezeConfirmTitle}
          tone={confirmFreeze ? "danger" : "default"}
          confirmLabel={confirmFreeze ? T.detail.freezeConfirm : T.detail.unfreezeConfirm}
          busy={freezeMutation.isPending}
          onCancel={() => {
            setConfirmFreeze(null);
          }}
          onConfirm={() => {
            freezeMutation.mutate(confirmFreeze);
          }}
        >
          <p>
            {fill(confirmFreeze ? T.detail.freezeConfirmBody : T.detail.unfreezeConfirmBody, {
              title: merchant.title,
            })}
          </p>
        </ConfirmDialog>
      )}

      {pendingCredit !== null && (
        <ConfirmDialog
          title={T.credit.confirmTitle}
          confirmLabel={T.credit.confirm}
          busy={creditMutation.isPending}
          onCancel={() => {
            setPendingCredit(null);
          }}
          onConfirm={confirmCredit}
        >
          <p>
            {fill(T.credit.confirmBody, {
              title: merchant.title,
              amount: formatUsd(pendingCredit),
            })}
          </p>
        </ConfirmDialog>
      )}
    </div>
  );
}
