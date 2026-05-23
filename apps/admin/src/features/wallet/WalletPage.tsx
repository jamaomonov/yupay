import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ScrollText, Search } from "lucide-react";

import { Button, Input } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { DataTable, type Column } from "@/components/DataTable";
import { Tabs, type TabDescriptor } from "@/components/Tabs";
import { useToast } from "@/components/Toast";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import type {
  AccountWithBalance,
  AdjustmentsListOut,
  AdminUserLedgerOut,
  Transaction,
} from "./types";

const ADJUST_KINDS = [
  { value: "user_wallet", label: "user_wallet" },
  { value: "user_cashback", label: "user_cashback" },
  { value: "user_promo_credit", label: "user_promo_credit" },
] as const;

/** Pre-selected codes finance / support use most often. The select renders
 *  the human label, but we persist the canonical code in `reason` so the
 *  ledger feed stays grep-able by `reason: CASHBACK_GRANT`. */
const REASON_PRESETS = [
  { code: "CASHBACK_GRANT", label: "Кэшбек — выдача" },
  { code: "MANUAL_TOPUP", label: "Пополнение вручную" },
  { code: "REFUND_CORRECTION", label: "Корректировка возврата" },
  { code: "GOODWILL", label: "Goodwill / компенсация" },
  { code: "INCIDENT_CREDIT", label: "Кредит после инцидента" },
  { code: "OTHER", label: "Другое (укажи детально)" },
] as const;

type WalletTab = "lookup" | "mine";

export function WalletPage() {
  const [tab, setTab] = useState<WalletTab>("lookup");

  const tabs: TabDescriptor<WalletTab>[] = [
    { id: "lookup", label: "Поиск пользователя", icon: Search },
    { id: "mine", label: "Мои корректировки", icon: ScrollText },
  ];

  return (
    <div>
      <PageHeader
        title="Кошелёк"
        description="Просмотр ledger'а пользователя + ручная корректировка."
      />
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={tabs}
        ariaLabel="Wallet sections"
        className="mb-5"
      />
      {tab === "lookup" ? <LookupTab /> : <MineTab />}
    </div>
  );
}

// ---------- lookup tab ----------

function LookupTab() {
  const qc = useQueryClient();
  const toast = useToast();
  const [searchParams] = useSearchParams();
  // Customer 360 deep-links here via /wallet?user_id=<uuid>; pre-fill
  // the lookup so the operator does not have to copy-paste the id.
  const initialUserId = searchParams.get("user_id") ?? "";
  const [userIdInput, setUserIdInput] = useState(initialUserId);
  const [activeUserId, setActiveUserId] = useState<string>(initialUserId);
  // Catch the case where Customer 360 → /wallet swap happens while the
  // tab is already mounted (React Router does not remount the page).
  useEffect(() => {
    const fromUrl = searchParams.get("user_id");
    if (fromUrl && fromUrl !== activeUserId) {
      setUserIdInput(fromUrl);
      setActiveUserId(fromUrl);
    }
    // activeUserId deliberately omitted: we only want to react to URL
    // changes, not loop when the operator clicks lookup manually.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);
  const [adjustKind, setAdjustKind] =
    useState<(typeof ADJUST_KINDS)[number]["value"]>("user_cashback");
  const [adjustCurrency, setAdjustCurrency] = useState("USD");
  const [adjustAmount, setAdjustAmount] = useState("");
  const [reasonPreset, setReasonPreset] =
    useState<(typeof REASON_PRESETS)[number]["code"]>("CASHBACK_GRANT");
  const [reasonDetail, setReasonDetail] = useState("");

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
      toast.success("Транзакция записана в ledger.");
      setAdjustAmount("");
      setReasonDetail("");
      void qc.invalidateQueries({ queryKey: qk.walletUser(activeUserId) });
      void qc.invalidateQueries({ queryKey: qk.walletAdjustments });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  const lookup = () => { setActiveUserId(userIdInput.trim()); };

  const submitAdjust = () => {
    if (!activeUserId) {
      toast.error("Сначала найди пользователя.");
      return;
    }
    if (!adjustAmount.trim()) {
      toast.error("Введи сумму.");
      return;
    }
    // OTHER must have a free-text explanation; other presets may stand
    // on their own, with the detail field used for optional flavour.
    if (reasonPreset === "OTHER" && reasonDetail.trim().length < 4) {
      toast.error("Для «Другое» нужны детали (≥ 4 символа).");
      return;
    }
    const finalReason = reasonDetail.trim()
      ? `${reasonPreset}: ${reasonDetail.trim()}`
      : reasonPreset;
    adjustMutation.mutate({
      user_id: activeUserId,
      kind: adjustKind,
      currency: adjustCurrency.toUpperCase(),
      amount: adjustAmount.trim(),
      reason: finalReason,
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
          <span className="text-xs text-[var(--text-secondary)]">{a.owner_type}</span>
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
              ? "text-[var(--success-fg)]"
              : "text-[var(--text-secondary)]"
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
      <section className="mb-6 flex flex-wrap items-end gap-3">
        <div className="grow">
          <label className="text-xs font-medium uppercase text-[var(--text-secondary)]">
            User ID
          </label>
          <Input
            value={userIdInput}
            onChange={(e) => { setUserIdInput(e.target.value); }}
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
            <h2 className="mb-3 text-sm font-semibold uppercase text-[var(--text-secondary)]">
              Счета
            </h2>
            <DataTable
              rows={ledgerQuery.data.accounts}
              columns={accountColumns}
              rowKey={(a) => a.id}
              empty="У пользователя пока нет ни одного счёта."
            />
          </section>

          <section className="mb-6 rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4">
            <h2 className="mb-3 text-sm font-semibold">Ручная корректировка</h2>
            <p className="mb-3 text-xs text-[var(--text-secondary)]">
              Положительная сумма — кредит пользователю; отрицательная — клавбэк.
              В ledger пишется пара проводок:{" "}
              <code>D user_&lt;kind&gt; / C house_promo_expense</code>.
            </p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
              <div>
                <label className="text-xs uppercase text-[var(--text-secondary)]">
                  Счёт
                </label>
                <select
                  value={adjustKind}
                  onChange={(e) =>
                    { setAdjustKind(
                      e.target.value as (typeof ADJUST_KINDS)[number]["value"],
                    ); }
                  }
                  className="mt-1 h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm"
                >
                  {ADJUST_KINDS.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs uppercase text-[var(--text-secondary)]">
                  Валюта
                </label>
                <Input
                  value={adjustCurrency}
                  onChange={(e) => { setAdjustCurrency(e.target.value); }}
                  maxLength={3}
                  className="mt-1 uppercase"
                />
              </div>
              <div>
                <label className="text-xs uppercase text-[var(--text-secondary)]">
                  Сумма
                </label>
                <Input
                  value={adjustAmount}
                  onChange={(e) => { setAdjustAmount(e.target.value); }}
                  inputMode="decimal"
                  placeholder="5.00 или -3.50"
                  className="mt-1 font-mono"
                />
              </div>
              <div>
                <label className="text-xs uppercase text-[var(--text-secondary)]">
                  Причина (preset)
                </label>
                <select
                  value={reasonPreset}
                  onChange={(e) =>
                    { setReasonPreset(
                      e.target.value as (typeof REASON_PRESETS)[number]["code"],
                    ); }
                  }
                  className="mt-1 h-10 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 text-sm"
                >
                  {REASON_PRESETS.map((r) => (
                    <option key={r.code} value={r.code}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="md:col-span-4">
                <label className="text-xs uppercase text-[var(--text-secondary)]">
                  Детали{" "}
                  {reasonPreset === "OTHER" ? (
                    <span className="text-[var(--danger-fg)]">
                      (обязательно для «Другое»)
                    </span>
                  ) : (
                    <span>(опционально, попадёт в audit-feed)</span>
                  )}
                </label>
                <Input
                  value={reasonDetail}
                  onChange={(e) => { setReasonDetail(e.target.value); }}
                  placeholder="например: компенсация за задержку выдачи кода"
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
              <p className="text-xs text-[var(--text-secondary)]">
                В audit: <code className="font-mono">{reasonPreset}</code>
                {reasonDetail.trim() ? `: ${reasonDetail.trim()}` : ""}
              </p>
            </div>
          </section>

          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase text-[var(--text-secondary)]">
              Последние транзакции
            </h2>
            <TransactionsList items={ledgerQuery.data.recent_transactions} />
          </section>
        </>
      )}

      {activeUserId && ledgerQuery.isError && (
        <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-6 text-sm text-[var(--danger)]">
          Не удалось загрузить ledger пользователя.
        </div>
      )}

      {!activeUserId && (
        <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-10 text-center text-sm text-[var(--text-secondary)]">
          Введи user_id, чтобы посмотреть счета и историю.
        </div>
      )}
    </div>
  );
}

// ---------- mine tab ----------

function MineTab() {
  const [scope, setScope] = useState<"me" | "all">("me");

  const q = useQuery<AdjustmentsListOut>({
    queryKey: [...qk.walletAdjustments, scope],
    queryFn: () =>
      apiGet<AdjustmentsListOut>(
        `/api/v1/admin/wallet/adjustments?actor=${scope}&limit=50`,
      ),
    refetchInterval: 30_000,
  });

  const items = q.data?.items ?? [];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <p className="text-sm text-[var(--text-secondary)]">
          Лог последних <code>admin.adjust</code> транзакций. Используй для
          сверки «что я сегодня правил» или быстрого аудита коллеги.
        </p>
        <div className="flex items-center gap-2 text-sm">
          <label className="text-[var(--text-secondary)]">Видимость:</label>
          <select
            value={scope}
            onChange={(e) => { setScope(e.target.value as "me" | "all"); }}
            className="h-10 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3"
          >
            <option value="me">Только мои</option>
            <option value="all">Все админы</option>
          </select>
        </div>
      </header>

      {q.isError && (
        <p className="text-sm text-[var(--danger)]">Ошибка загрузки.</p>
      )}

      {items.length === 0 && !q.isPending ? (
        <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-10 text-center text-sm text-[var(--text-secondary)]">
          Ещё ни одной ручной корректировки.
        </div>
      ) : (
        <AdjustmentsFeed items={items} />
      )}
    </div>
  );
}

function AdjustmentsFeed({ items }: { items: Transaction[] }) {
  // Each tx has 2 postings: user-side and house-side. The user-side line
  // gives us the amount delta (+/-) and the user_id from reference_id.
  return (
    <ul className="space-y-3">
      {items.map((tx) => {
        const userId = tx.reference_id ?? null;
        const reason =
          typeof tx.extra_metadata.reason === "string"
            ? tx.extra_metadata.reason
            : "";
        const presetCode = reason.includes(":") ? reason.split(":")[0]?.trim() : reason;
        const detail = reason.includes(":") ? reason.split(":").slice(1).join(":").trim() : "";
        return (
          <li
            key={tx.id}
            className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4 text-sm"
          >
            <header className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="flex flex-wrap items-baseline gap-2">
                <code className="rounded bg-[var(--bg-muted)] px-1.5 py-0.5 text-xs">
                  {presetCode || "—"}
                </code>
                {userId ? (
                  <Link
                    to={`/customers/${userId}`}
                    className="font-mono text-xs underline-offset-2 hover:underline"
                  >
                    user {userId.slice(0, 8)}…
                  </Link>
                ) : (
                  <span className="font-mono text-xs text-[var(--text-secondary)]">
                    user —
                  </span>
                )}
                {tx.actor && (
                  <span className="text-xs text-[var(--text-secondary)]">
                    by {tx.actor}
                  </span>
                )}
              </div>
              <span className="text-xs text-[var(--text-secondary)]">
                {new Date(tx.created_at).toLocaleString("ru")}
              </span>
            </header>
            <ul className="mt-2 space-y-0.5 font-mono text-xs">
              {tx.postings.map((p) => (
                <li key={p.id} className="flex justify-between">
                  <span>
                    {p.direction === "D" ? "↓ D" : "↑ C"} ·{" "}
                    {p.account_id.slice(0, 8)}…
                  </span>
                  <span>
                    {formatMoney(p.amount)} {p.currency}
                  </span>
                </li>
              ))}
            </ul>
            {detail && (
              <p className="mt-2 text-xs text-[var(--text-secondary)]">
                «{detail}»
              </p>
            )}
          </li>
        );
      })}
    </ul>
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
      <div className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-6 text-center text-sm text-[var(--text-secondary)]">
        История пустая.
      </div>
    );
  }
  return (
    <div className="space-y-3">
      {items.map((tx) => (
        <article
          key={tx.id}
          className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4 text-sm"
        >
          <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
            <div>
              <span className="font-medium">{tx.kind}</span>
              {tx.actor && (
                <span className="ml-2 text-xs text-[var(--text-secondary)]">
                  by {tx.actor}
                </span>
              )}
            </div>
            <span className="text-xs text-[var(--text-secondary)]">
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
          {typeof tx.extra_metadata.reason === "string" &&
            tx.extra_metadata.reason.length > 0 && (
              <p className="mt-2 text-xs text-[var(--text-secondary)]">
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
