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
 *
 * The optional `order_id` (M3b Task 2) settles ONE failed order: the amount
 * then lands in that order's `refunded_usd` and carries the reseller's own
 * `merchant_order_id` onto their statement, instead of being an anonymous
 * top-up they cannot tie to anything. It is subject to the same replay rule
 * as the amount and one more fact besides — **a posted attribution cannot be
 * re-pointed**, so a replay that ignored it is unfixable, which is why it
 * shares the mismatch banner rather than a quieter signal.
 *
 * The id is validated here before it is sent, because the API's refusal for a
 * malformed one is a deliberate `404 order_not_found` — the same answer as
 * "not this merchant's order", so an operator who pasted the reseller's
 * `merchant_order_id` would read "no such order" and hunt in the wrong place.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { Plug, Snowflake, Sun, Users, Wallet } from "lucide-react";
import { useId, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  T,
  creditDeposit,
  fetchMerchants,
  fill,
  formatUsd,
  parseOrderId,
  parseUsdAmount,
  sameAmount,
  setMerchantFrozen,
  type DepositCreditOut,
  type MerchantListOut,
  type MerchantOut,
} from "./api";
import { DepositDebitCard } from "./DepositDebitCard";
import { MerchantKeysCard } from "./MerchantKeysCard";
import { MerchantLedgerCard } from "./MerchantLedgerCard";
import { MerchantMarkupCard } from "./MerchantMarkupCard";
import { MerchantUsersCard } from "./MerchantUsersCard";
import { MerchantWebhookCard } from "./MerchantWebhookCard";

import type { ApiError } from "@/lib/api";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { MoneyInput } from "@/components/MoneyInput";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { Spinner } from "@/components/States";
import { StatusChip } from "@/components/StatusChip";
import { Tabs } from "@/components/Tabs";
import { useToast } from "@/components/Toast";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";
import { useSearchParamsState } from "@/lib/useSearchParamsState";

/** The three errands this page exists for. */
type MerchantTab = "money" | "integration" | "people";

/** What the UI renders where a value is absent — the ledger table's own dash. */
const EMPTY_VALUE = "—";

export function MerchantDetail() {
  const { id = "" } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const amountFieldId = useId();
  const noteFieldId = useId();
  const orderFieldId = useId();

  // There is no single-merchant GET — the list is one grouped query and the
  // detail reuses its cache entry.
  const listQuery = useQuery<MerchantListOut>({
    queryKey: qk.merchants(),
    queryFn: fetchMerchants,
  });
  const merchant = listQuery.data?.items.find((m) => m.id === id) ?? null;

  // ----- freeze / unfreeze -----
  const [confirmFreeze, setConfirmFreeze] = useState<boolean | null>(null);
  const [tab, setTab] = useSearchParamsState<MerchantTab>("tab", "money");
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
  const [orderId, setOrderId] = useState("");
  /** Canonical amount + order awaiting confirmation; `null` = no dialog. */
  const [pendingCredit, setPendingCredit] = useState<{
    amount: string;
    orderId: string | null;
  } | null>(null);
  const [lastCredit, setLastCredit] = useState<DepositCreditOut | null>(null);
  /** What the ledger booked vs what was typed, per field it can disagree on. */
  const [mismatch, setMismatch] = useState<{
    amount: { booked: string; typed: string } | null;
    order: { booked: string; typed: string } | null;
  } | null>(null);
  const creditKeyRef = useRef("");
  // `isPending` re-renders one tick after `mutate` — a same-tick double-click
  // would fire twice. The ref flips synchronously.
  const creditInFlightRef = useRef(false);

  const creditMutation = useMutation<
    DepositCreditOut,
    ApiError,
    { amount: string; note: string | null; order_id: string | null }
  >({
    mutationFn: (body) => creditDeposit(id, body, creditKeyRef.current),
    onSettled: () => {
      creditInFlightRef.current = false;
    },
    onSuccess: (data, vars) => {
      setPendingCredit(null);
      setLastCredit(data);
      // A replayed key returns the ORIGINAL transaction and ignores every
      // parameter of this request. Both things it can silently disagree with
      // are checked; either one is a loud banner and no success toast.
      const amountOff = !sameAmount(data.amount, vars.amount);
      const orderOff = data.order_id !== vars.order_id;
      if (amountOff || orderOff) {
        setMismatch({
          amount: amountOff ? { booked: data.amount, typed: vars.amount } : null,
          order: orderOff
            ? { booked: data.order_id ?? EMPTY_VALUE, typed: vars.order_id ?? EMPTY_VALUE }
            : null,
        });
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
        setOrderId("");
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
    // Empty is the ordinary prepayment; anything typed must be a real id
    // before it is sent, or the 404 will read as "no such order".
    const typedOrder = orderId.trim();
    const parsedOrder = typedOrder ? parseOrderId(typedOrder) : null;
    if (typedOrder && parsedOrder === null) {
      toast.error(T.credit.orderInvalid);
      return;
    }
    // One key per logical attempt (minted here, not in the confirm click):
    // retries of this attempt replay it, the next submit mints a fresh one.
    creditKeyRef.current = `merchant-topup-${crypto.randomUUID()}`;
    setMismatch(null);
    setPendingCredit({ amount: parsed, orderId: parsedOrder });
  };

  const confirmCredit = () => {
    if (pendingCredit === null || creditInFlightRef.current) return;
    creditInFlightRef.current = true;
    creditMutation.mutate({
      amount: pendingCredit.amount,
      note: note.trim() ? note.trim() : null,
      order_id: pendingCredit.orderId,
    });
  };

  const isFrozen = merchant?.status === "frozen";

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

      {/* An exact filter on the id, not a search for the title: two resellers
          whose names share a word land in the same search, and a title is
          something an operator can rename. */}
      <p className="mb-6">
        <Link
          to={`/orders?merchant_id=${encodeURIComponent(id)}`}
          className="text-sm font-semibold text-[var(--accent-soft-fg)]"
        >
          {T.detail.ordersLink}
        </Link>
      </p>

      {mismatch && (
        <div
          role="alert"
          className="mb-5 space-y-2 rounded-lg border border-[var(--danger)] bg-[var(--danger-soft)] p-4 text-sm font-medium text-[var(--danger-fg)]"
        >
          {mismatch.amount && (
            <p>
              {fill(T.credit.replayMismatch, {
                booked: formatUsd(mismatch.amount.booked),
                typed: formatUsd(mismatch.amount.typed),
              })}
            </p>
          )}
          {mismatch.order && (
            <p>
              {fill(T.credit.replayOrderMismatch, {
                booked: mismatch.order.booked,
                typed: mismatch.order.typed,
              })}
            </p>
          )}
        </div>
      )}

      {/* Ten stacked sections made this page a scroll on a phone, and the
          admin is used on one. Grouped rather than collapsed: an operator
          arrives here for one of three errands — move money, fix an
          integration, or find out why somebody cannot sign in — and each tab
          is one of them. The identity strip above stays put, because "who is
          this and is anything wrong" is the question all three share.

          The active tab lives in the URL, like every other filter in this
          admin, so a refresh or a back button lands where you were. */}
      <Tabs
        value={tab}
        onChange={(next) => {
          setTab(next);
        }}
        ariaLabel={T.tabs.aria}
        tabs={[
          { id: "money", label: T.tabs.money, icon: Wallet },
          { id: "integration", label: T.tabs.integration, icon: Plug },
          { id: "people", label: T.tabs.people, icon: Users },
        ]}
        className="mb-5"
      />

      {tab === "money" && (
        <>
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
                <label
                  htmlFor={noteFieldId}
                  className="text-xs uppercase text-[var(--text-secondary)]"
                >
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
              <div className="md:col-span-3">
                <label
                  htmlFor={orderFieldId}
                  className="text-xs uppercase text-[var(--text-secondary)]"
                >
                  {T.credit.orderLabel} <span className="normal-case">{T.credit.orderHint}</span>
                </label>
                <Input
                  id={orderFieldId}
                  value={orderId}
                  onChange={(e) => {
                    setOrderId(e.target.value);
                  }}
                  placeholder={T.credit.orderPlaceholder}
                  className="mt-1 font-mono"
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
                  {lastCredit.order_id !== null && (
                    // Off the response, not off the form: this is what the ledger
                    // actually booked, and it is the merchant's `refunded_usd`.
                    <span className="ml-2 font-mono">
                      {fill(T.credit.resultOrder, { order: lastCredit.order_id })}
                    </span>
                  )}
                </p>
              )}
            </div>
          </section>

          <DepositDebitCard
            merchantId={id}
            merchantTitle={merchant.title}
            balance={merchant.deposit_balance}
            onBalance={(balance) => {
              patchList({ ...merchant, deposit_balance: balance });
            }}
          />

          {/* Credentials after money, before the ledger: the money cards are what
          an operator opens this page for, and the ledger is the long tail they
          scroll to. The two integration cards sit between because they are
          what a support conversation needs — "is his key live", "are his
          webhooks arriving" — and both were answerable only by psql before. */}
          {/* Price before credentials: what this reseller pays is a commercial
          decision an operator makes on purpose, and the integration cards
          below are what they open when something is broken. */}
          <MerchantMarkupCard merchant={merchant} onChange={patchList} />
          <MerchantLedgerCard merchantId={id} />
        </>
      )}

      {tab === "integration" && (
        <>
          <MerchantKeysCard merchantId={id} />
          <MerchantWebhookCard merchantId={id} />
        </>
      )}

      {tab === "people" && <MerchantUsersCard merchantId={id} />}

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
              amount: formatUsd(pendingCredit.amount),
            })}
          </p>
          {pendingCredit.orderId !== null && (
            <p className="mt-2">
              {fill(T.credit.confirmBodyOrder, { order: pendingCredit.orderId })}
            </p>
          )}
        </ConfirmDialog>
      )}
    </div>
  );
}
