/**
 * Customer 360 — `/customers/:id`.
 *
 * Single aggregated read (`GET /api/v1/admin/customers/{id}/overview`) drives the
 * whole page so a support operator can see user, recent orders, recent payments,
 * open fulfillment tasks, wallet balances, stats and risk flags in one place.
 *
 * Per ADR-0017 quick actions are grouped semantically (support / finance) even
 * though there's only one admin role today — that way the future role gate is a
 * cheap drop-in.
 */

import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  CalendarClock,
  Globe,
  Mail,
  MessageCircle,
  Receipt,
  Send,
  Wallet,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button } from "@yupay/ui";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { type ApiError, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import {
  type CustomerOrderSummary,
  type CustomerOverviewOut,
  type CustomerPaymentSummary,
  type CustomerTaskSummary,
  RISK_FLAG_LABEL,
  RISK_FLAG_TONE,
} from "./types";

export function CustomerPage() {
  const params = useParams<{ id: string }>();
  const userId = params.id ?? "";
  const navigate = useNavigate();
  const query = useQuery<CustomerOverviewOut, ApiError>({
    queryKey: qk.customerOverview(userId),
    queryFn: () =>
      apiGet<CustomerOverviewOut>(`/api/v1/admin/customers/${userId}/overview`),
    enabled: Boolean(userId),
    refetchInterval: 30_000,
  });

  if (query.isError) {
    const status = query.error.status;
    return (
      <div>
        <PageHeader title="Карточка клиента" />
        <p className="text-sm text-[--color-danger]">
          {status === 404
            ? "Пользователь не найден."
            : status === 403
              ? "Доступ запрещён."
              : "Не удалось загрузить карточку клиента."}
        </p>
      </div>
    );
  }

  if (!query.data) {
    return (
      <div>
        <PageHeader title="Карточка клиента" />
        <Spinner label="Загрузка карточки клиента…" />
      </div>
    );
  }

  const data = query.data;
  const goOrder = (orderId: string) => { void navigate(`/orders/${orderId}`); };
  return (
    <div className="space-y-6">
      <UserHeader data={data} />
      <Stats stats={data.stats} />
      <RecentOrders rows={data.recent_orders} onOpen={goOrder} />
      <RecentPayments rows={data.recent_payments} onOpen={goOrder} />
      <OpenTasks rows={data.open_fulfillment_tasks} onOpen={goOrder} />
      <WalletBalances balances={data.wallet_balances} />
    </div>
  );
}

function UserHeader({ data }: { data: CustomerOverviewOut }) {
  const u = data.user;
  const tg = u.telegram_link;
  const initials = (u.display_name ?? u.email ?? "??").slice(0, 2).toUpperCase();
  const telegramUrl = tg?.tg_username ? `https://t.me/${tg.tg_username}` : null;

  return (
    <header className="rounded-lg border bg-[--color-bg] p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-4 min-w-0">
          {u.photo_url ? (
            <img
              src={u.photo_url}
              alt=""
              className="size-14 rounded-full object-cover border border-[--color-border]"
            />
          ) : (
            <div
              className="size-14 rounded-full flex items-center justify-center font-semibold border border-[--color-border]"
              style={{ background: "var(--color-subtle)" }}
            >
              {initials}
            </div>
          )}
          <div className="min-w-0">
            <h1 className="text-xl font-semibold truncate">
              {u.display_name ?? u.email ?? "(без имени)"}
            </h1>
            <p className="font-mono text-xs text-[--color-muted] mt-0.5">{u.id}</p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-[--color-muted]">
              {u.email && (
                <span className="inline-flex items-center gap-1.5">
                  <Mail className="size-3.5" />
                  {u.email}
                </span>
              )}
              {tg && (
                <span className="inline-flex items-center gap-1.5">
                  <MessageCircle className="size-3.5" />
                  {tg.tg_username ? `@${tg.tg_username}` : `tg:${tg.tg_user_id.toString()}`}
                </span>
              )}
              <span className="inline-flex items-center gap-1.5">
                <Globe className="size-3.5" />
                {u.locale} · {u.display_currency}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <CalendarClock className="size-3.5" />
                {formatDate(u.created_at)}
              </span>
            </div>
            {data.risk_flags.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {data.risk_flags.map((flag) => (
                  <span
                    key={flag}
                    className={[
                      "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                      RISK_FLAG_TONE[flag] === "warn"
                        ? "bg-[--color-danger]/15 text-[--color-danger]"
                        : "bg-[--color-subtle] text-[--color-muted]",
                    ].join(" ")}
                  >
                    {RISK_FLAG_TONE[flag] === "warn" && <AlertTriangle className="size-3" />}
                    {RISK_FLAG_LABEL[flag]}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-start gap-2">
          {telegramUrl && (
            <a
              href={telegramUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-md border border-[--color-border] px-3 py-1.5 text-sm hover:bg-[--color-subtle]"
            >
              <Send className="size-4" />
              Telegram
              <ArrowUpRight className="size-3.5 text-[--color-muted]" />
            </a>
          )}
          <Link
            to={`/wallet?user=${u.id}`}
            className="inline-flex items-center gap-2 rounded-md border border-[--color-border] px-3 py-1.5 text-sm hover:bg-[--color-subtle]"
          >
            <Wallet className="size-4" />
            Кошелёк
          </Link>
          <Link
            to={`/audit?target_id=${u.id}`}
            className="inline-flex items-center gap-2 rounded-md border border-[--color-border] px-3 py-1.5 text-sm hover:bg-[--color-subtle]"
          >
            <Receipt className="size-4" />
            Аудит
          </Link>
        </div>
      </div>
    </header>
  );
}

function Stats({ stats }: { stats: CustomerOverviewOut["stats"] }) {
  return (
    <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Заказов всего" value={stats.total_orders} />
      <Stat label="Доставлено" value={stats.delivered_orders} tone="success" />
      <Stat
        label="Потрачено (USD)"
        value={formatMoney(stats.total_spent_usd)}
        accent
      />
      <Stat
        label="Failed-платежей"
        value={stats.failed_payments}
        tone={stats.failed_payments > 0 ? "warn" : "muted"}
      />
    </section>
  );
}

function Stat({
  label,
  value,
  accent,
  tone = "default",
}: {
  label: string;
  value: number | string;
  accent?: boolean;
  tone?: "success" | "warn" | "muted" | "default";
}) {
  const cls = accent
    ? "text-[--color-brand]"
    : tone === "warn"
      ? "text-[--color-danger]"
      : tone === "success"
        ? "text-[--success-fg]"
        : tone === "muted"
          ? "text-[--color-muted]"
          : "text-[--color-fg]";
  return (
    <article className="rounded-lg border bg-[--color-bg] p-4">
      <div className="text-xs uppercase tracking-wide text-[--color-muted]">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${cls}`}>{value}</div>
    </article>
  );
}

function RecentOrders({
  rows,
  onOpen,
}: {
  rows: CustomerOrderSummary[];
  onOpen: (orderId: string) => void;
}) {
  const columns: Column<CustomerOrderSummary>[] = [
    {
      key: "id",
      header: "ID",
      render: (o) => <span className="font-mono text-xs">{o.id.slice(0, 8)}…</span>,
      className: "w-24",
    },
    { key: "status", header: "Статус", render: (o) => o.status, className: "w-32" },
    {
      key: "items",
      header: "Позиции",
      render: (o) => o.items_count.toString(),
      className: "w-20",
    },
    {
      key: "total",
      header: "Сумма",
      render: (o) => `${formatMoney(o.total_charged)} ${o.currency}`,
      className: "w-32 text-right",
    },
    { key: "created", header: "Создан", render: (o) => formatDate(o.created_at) },
    {
      key: "delivered",
      header: "Доставлен",
      render: (o) => formatDate(o.delivered_at),
    },
  ];
  return (
    <Section title="Последние заказы" count={rows.length}>
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(o) => o.id}
        empty="Заказов пока нет."
        onRowClick={(o) => { onOpen(o.id); }}
      />
    </Section>
  );
}

function RecentPayments({
  rows,
  onOpen,
}: {
  rows: CustomerPaymentSummary[];
  onOpen: (orderId: string) => void;
}) {
  const columns: Column<CustomerPaymentSummary>[] = [
    {
      key: "id",
      header: "ID",
      render: (p) => <span className="font-mono text-xs">{p.id.slice(0, 8)}…</span>,
      className: "w-24",
    },
    { key: "provider", header: "Провайдер", render: (p) => p.provider, className: "w-32" },
    { key: "status", header: "Статус", render: (p) => p.status, className: "w-28" },
    {
      key: "amount",
      header: "Сумма",
      render: (p) => `${formatMoney(p.amount)} ${p.currency}`,
      className: "w-32 text-right",
    },
    {
      key: "external_id",
      header: "External",
      render: (p) =>
        p.external_id ? (
          <span className="font-mono text-xs">{p.external_id}</span>
        ) : (
          <span className="text-[--color-muted]">—</span>
        ),
    },
    { key: "created", header: "Создан", render: (p) => formatDate(p.created_at) },
  ];
  return (
    <Section title="Последние платежи" count={rows.length}>
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(p) => p.id}
        empty="Платежей нет."
        onRowClick={(p) => { onOpen(p.order_id); }}
      />
    </Section>
  );
}

function OpenTasks({
  rows,
  onOpen,
}: {
  rows: CustomerTaskSummary[];
  onOpen: (orderId: string) => void;
}) {
  if (rows.length === 0) return null;
  const columns: Column<CustomerTaskSummary>[] = [
    {
      key: "id",
      header: "ID",
      render: (t) => <span className="font-mono text-xs">{t.id.slice(0, 8)}…</span>,
      className: "w-24",
    },
    { key: "supplier", header: "Поставщик", render: (t) => t.supplier, className: "w-32" },
    { key: "status", header: "Статус", render: (t) => t.status, className: "w-28" },
    {
      key: "error",
      header: "Ошибка",
      render: (t) =>
        t.last_error ? (
          <span className="text-[--color-danger]">{t.last_error}</span>
        ) : (
          <span className="text-[--color-muted]">—</span>
        ),
    },
    { key: "created", header: "Создан", render: (t) => formatDate(t.created_at) },
  ];
  return (
    <Section title="Открытые задачи fulfilment" count={rows.length} tone="warn">
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(t) => t.id}
        empty="Открытых задач нет."
        onRowClick={(t) => { onOpen(t.order_id); }}
      />
    </Section>
  );
}

function WalletBalances({
  balances,
}: {
  balances: CustomerOverviewOut["wallet_balances"];
}) {
  return (
    <Section title="Кошелёк" count={balances.length}>
      {balances.length === 0 ? (
        <p className="text-sm text-[--color-muted]">Аккаунтов кошелька нет.</p>
      ) : (
        <ul className="space-y-1.5">
          {balances.map((b) => (
            <li
              key={b.account_id}
              className="flex items-center justify-between rounded-md border bg-[--color-bg] px-3 py-2 text-sm"
            >
              <span className="text-[--color-muted]">{b.kind}</span>
              <span className="font-mono">
                {formatMoney(b.balance)} {b.currency}
              </span>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Section({
  title,
  count,
  tone,
  children,
}: {
  title: string;
  count: number;
  tone?: "warn";
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[--color-muted]">
          {title}
        </h2>
        <span
          className={[
            "text-xs",
            tone === "warn" && count > 0
              ? "text-[--color-danger]"
              : "text-[--color-muted]",
          ].join(" ")}
        >
          {count.toString()}
        </span>
      </div>
      {children}
    </section>
  );
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("ru", {
    year: "2-digit",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatMoney(value: string): string {
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n)) return value;
  return n.toLocaleString("ru", { maximumFractionDigits: 2 });
}
