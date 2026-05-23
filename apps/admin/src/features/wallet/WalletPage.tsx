import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { Button, Input } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import type {
  AccountWithBalance,
  AdminUserLedgerOut,
  Transaction,
} from "./types";

const ADJUST_KINDS = [
  { value: "user_wallet", label: "user_wallet" },
  { value: "user_cashback", label: "user_cashback" },
  { value: "user_promo_credit", label: "user_promo_credit" },
] as const;

export function WalletPage() {
  const qc = useQueryClient();
  const [userIdInput, setUserIdInput] = useState("");
  const [activeUserId, setActiveUserId] = useState<string>("");
  const [adjustKind, setAdjustKind] =
    useState<(typeof ADJUST_KINDS)[number]["value"]>("user_cashback");
  const [adjustCurrency, setAdjustCurrency] = useState("USD");
  const [adjustAmount, setAdjustAmount] = useState("");
  const [adjustReason, setAdjustReason] = useState("");
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const ledgerQuery = useQuery<AdminUserLedgerOut>({
    queryKey: qk.walletUser(activeUserId),
    queryFn: () =>
      apiGet<AdminUserLedgerOut>(
        `/api/v1/admin/wallet/${activeUserId}?limit=50`,
      ),
    enabled: Boolean(activeUserId),
  });

  const adjustMutation = useMutation<Transaction, ApiError, AdjustBody>({
    mutationFn: (body) =>
      apiPost<Transaction>("/api/v1/admin/wallet/adjust", body),
    onSuccess: () => {
      setFeedback("Транзакция записана.");
      setError(null);
      setAdjustAmount("");
      setAdjustReason("");
      void qc.invalidateQueries({ queryKey: qk.walletUser(activeUserId) });
    },
    onError: (err) => {
      setError(formatApiError(err));
      setFeedback(null);
    },
  });

  const lookup = () => {
    setActiveUserId(userIdInput.trim());
    setFeedback(null);
    setError(null);
  };

  const submitAdjust = () => {
    setError(null);
    setFeedback(null);
    if (!activeUserId) {
      setError("Сначала найди пользователя.");
      return;
    }
    if (!adjustAmount.trim()) {
      setError("Введи сумму.");
      return;
    }
    if (adjustReason.trim().length < 4) {
      setError("Причина: минимум 4 символа.");
      return;
    }
    adjustMutation.mutate({
      user_id: activeUserId,
      kind: adjustKind,
      currency: adjustCurrency.toUpperCase(),
      amount: adjustAmount.trim(),
      reason: adjustReason.trim(),
      idempotency_key: `admin-adjust-${crypto.randomUUID()}`,
    });
  };

  const accountColumns: Column<AccountWithBalance>[] = [
    {
      key: "kind",
      header: "Счёт",
      render: (a) => (
        <div className="flex flex-col">
          <span className="text-sm">{a.kind}</span>
          <span className="text-xs text-[--text-secondary]">{a.owner_type}</span>
        </div>
      ),
    },
    { key: "currency", header: "Валюта", render: (a) => a.currency, className: "w-20" },
    {
      key: "balance",
      header: "Баланс",
      render: (a) => (
        <span className="font-medium">{formatMoney(a.balance)}</span>
      ),
      className: "w-32 text-right",
    },
    {
      key: "status",
      header: "Статус",
      render: (a) => (
        <span
          className={
            a.status === "active"
              ? "text-[--success]"
              : "text-[--text-secondary]"
          }
        >
          {a.status}
        </span>
      ),
      className: "w-24",
    },
  ];

  return (
    <div>
      <PageHeader
        title="Кошелёк"
        description="Просмотр ledger'а пользователя + ручная корректировка."
      />

      <section className="mb-6 flex flex-wrap items-end gap-3">
        <div className="grow">
          <label className="text-xs font-medium uppercase text-[--text-secondary]">
            User ID
          </label>
          <Input
            value={userIdInput}
            onChange={(e) => setUserIdInput(e.target.value)}
            placeholder="UUID v7"
            className="mt-1 font-mono text-xs"
          />
        </div>
        <Button onClick={lookup} disabled={!userIdInput.trim()}>
          Открыть ledger
        </Button>
      </section>

      {activeUserId && ledgerQuery.data && (
        <>
          <section className="mb-6">
            <h2 className="mb-3 text-sm font-semibold uppercase text-[--text-secondary]">
              Счета
            </h2>
            <DataTable
              rows={ledgerQuery.data.accounts}
              columns={accountColumns}
              rowKey={(a) => a.id}
              empty="У пользователя пока нет ни одного счёта."
            />
          </section>

          <section className="mb-6 rounded-lg border bg-[--bg-surface] p-4">
            <h2 className="mb-3 text-sm font-semibold">Ручная корректировка</h2>
            <p className="mb-3 text-xs text-[--text-secondary]">
              Положительная сумма — кредит пользователю; отрицательная — клавбэк.
              В ledger пишется пара проводок:{" "}
              <code>D user_&lt;kind&gt; / C house_promo_expense</code>.
            </p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              <div>
                <label className="text-xs uppercase text-[--text-secondary]">
                  Счёт
                </label>
                <select
                  value={adjustKind}
                  onChange={(e) =>
                    setAdjustKind(
                      e.target.value as (typeof ADJUST_KINDS)[number]["value"],
                    )
                  }
                  className="mt-1 h-10 w-full rounded-md border border-[--border-default] bg-[--bg-surface] px-3 text-sm"
                >
                  {ADJUST_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs uppercase text-[--text-secondary]">
                  Валюта
                </label>
                <Input
                  value={adjustCurrency}
                  onChange={(e) => setAdjustCurrency(e.target.value)}
                  maxLength={3}
                  className="mt-1 uppercase"
                />
              </div>
              <div>
                <label className="text-xs uppercase text-[--text-secondary]">
                  Сумма
                </label>
                <Input
                  value={adjustAmount}
                  onChange={(e) => setAdjustAmount(e.target.value)}
                  inputMode="decimal"
                  placeholder="5.00 или -3.50"
                  className="mt-1 font-mono"
                />
              </div>
              <div>
                <label className="text-xs uppercase text-[--text-secondary]">
                  Причина
                </label>
                <Input
                  value={adjustReason}
                  onChange={(e) => setAdjustReason(e.target.value)}
                  placeholder="например, компенсация инцидента"
                  className="mt-1"
                />
              </div>
            </div>
            <div className="mt-4 flex items-center gap-3">
              <Button
                onClick={submitAdjust}
                disabled={adjustMutation.isPending}
              >
                {adjustMutation.isPending ? "Записываем…" : "Записать"}
              </Button>
              {feedback && (
                <span className="text-sm text-[--success]">{feedback}</span>
              )}
              {error && (
                <span className="text-sm text-[--danger]">{error}</span>
              )}
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase text-[--text-secondary]">
              Последние транзакции
            </h2>
            <TransactionsList items={ledgerQuery.data.recent_transactions} />
          </section>
        </>
      )}

      {activeUserId && ledgerQuery.isError && (
        <div className="rounded-lg border bg-[--bg-surface] p-6 text-sm text-[--danger]">
          Не удалось загрузить ledger пользователя.
        </div>
      )}

      {!activeUserId && (
        <div className="rounded-lg border bg-[--bg-surface] p-10 text-center text-sm text-[--text-secondary]">
          Введи user_id, чтобы посмотреть счета и историю.
        </div>
      )}
    </div>
  );
}

interface AdjustBody {
  user_id: string;
  kind: string;
  currency: string;
  amount: string;
  reason: string;
  idempotency_key: string;
}

function TransactionsList({ items }: { items: Transaction[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-lg border bg-[--bg-surface] p-6 text-center text-sm text-[--text-secondary]">
        История пустая.
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {items.map((tx) => (
        <article
          key={tx.id}
          className="rounded-lg border bg-[--bg-surface] p-4 text-sm"
        >
          <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <span className="font-medium">{tx.kind}</span>
              {tx.actor && (
                <span className="ml-2 text-xs text-[--text-secondary]">
                  by {tx.actor}
                </span>
              )}
            </div>
            <span className="text-xs text-[--text-secondary]">
              {new Date(tx.created_at).toLocaleString("ru")}
            </span>
          </header>
          <ul className="space-y-0.5 font-mono text-xs">
            {tx.postings.map((p) => (
              <li key={p.id} className="flex justify-between">
                <span>
                  {p.direction === "D" ? "↓ D" : "↑ C"} · {p.account_id.slice(0, 8)}…
                </span>
                <span>
                  {formatMoney(p.amount)} {p.currency}
                </span>
              </li>
            ))}
          </ul>
          {typeof tx.extra_metadata?.reason === "string" &&
            tx.extra_metadata.reason.length > 0 && (
              <p className="mt-2 text-xs text-[--text-secondary]">
                «{tx.extra_metadata.reason}»
              </p>
            )}
        </article>
      ))}
    </div>
  );
}

function formatMoney(value: string): string {
  const n = Number.parseFloat(value);
  if (Number.isNaN(n)) return value;
  return n.toFixed(2);
}

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string; title?: string } | null;
  return body?.detail ?? body?.title ?? err.message;
}
