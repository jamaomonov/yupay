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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowUpRight,
  CalendarClock,
  Globe,
  Mail,
  MessageCircle,
  Receipt,
  Send,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Button } from "@yupay/ui";

import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { useToast } from "@/components/Toast";
import { type ApiError, api, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import type { UserAdminOut } from "@/features/users/types";

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
  const qc = useQueryClient();
  const toast = useToast();
  const query = useQuery<CustomerOverviewOut, ApiError>({
    queryKey: qk.customerOverview(userId),
    queryFn: () =>
      apiGet<CustomerOverviewOut>(`/api/v1/admin/customers/${userId}/overview`),
    enabled: Boolean(userId),
    refetchInterval: 30_000,
  });

  // Role management mutation — kept on the page so the header can stay
  // presentational and the toast / cache invalidation are wired up once.
  const setRoles = useMutation<UserAdminOut, ApiError, string[]>({
    mutationFn: (roles) =>
      api<UserAdminOut>(`/api/v1/admin/users/${userId}/roles`, {
        method: "PATCH",
        body: JSON.stringify({ roles }),
      }),
    onSuccess: (updated) => {
      toast.success(
        updated.roles.includes("admin")
          ? "Админ-роль выдана."
          : "Админ-роль снята.",
      );
      void qc.invalidateQueries({ queryKey: qk.customerOverview(userId) });
      void qc.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (err) => {
      toast.error(formatApiError(err));
    },
  });

  if (query.isError) {
    const status = query.error.status;
    return (
      <div>
        <PageHeader title="Карточка клиента" />
        <p className="text-sm text-[var(--danger)]">
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
  const isAdmin = data.user.roles.includes("admin");
  return (
    <div className="space-y-6">
      <UserHeader
        data={data}
        onToggleAdmin={() => {
          const action = isAdmin ? "снять админ-роль" : "выдать админ-роль";
          const name = data.user.display_name ?? data.user.email ?? data.user.id.slice(0, 8);
          if (!window.confirm(`Точно ${action} у ${name}?`)) return;
          const next = isAdmin
            ? data.user.roles.filter((r) => r !== "admin")
            : [...new Set([...data.user.roles, "admin"])];
          setRoles.mutate(next);
        }}
        rolePending={setRoles.isPending}
      />
      <Stats stats={data.stats} />
      <RecentOrders rows={data.recent_orders} onOpen={goOrder} />
      <RecentPayments rows={data.recent_payments} onOpen={goOrder} />
      <OpenTasks rows={data.open_fulfillment_tasks} onOpen={goOrder} />
      <WalletBalances balances={data.wallet_balances} />
    </div>
  );
}

function UserHeader({
  data,
  onToggleAdmin,
  rolePending,
}: {
  data: CustomerOverviewOut;
  onToggleAdmin: () => void;
  rolePending: boolean;
}) {
  const u = data.user;
  const tg = u.telegram_link;
  const initials = (u.display_name ?? u.email ?? "??").slice(0, 2).toUpperCase();
  const telegramUrl = tg?.tg_username ? `https://t.me/${tg.tg_username}` : null;
  const isAdmin = u.roles.includes("admin");

  return (
    <header className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-4 min-w-0">
          {u.photo_url ? (
            <img
              src={u.photo_url}
              alt=""
              className="size-14 rounded-full object-cover border border-[var(--border-default)]"
            />
          ) : (
            <div
              className="size-14 rounded-full flex items-center justify-center font-semibold border border-[var(--border-default)]"
              style={{ background: "var(--bg-muted)" }}
            >
              {initials}
            </div>
          )}
          <div className="min-w-0">
            <h1 className="text-xl font-semibold truncate">
              {u.display_name ?? u.email ?? "(без имени)"}
            </h1>
            <p className="font-mono text-xs text-[var(--text-secondary)] mt-0.5">{u.id}</p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-sm text-[var(--text-secondary)]">
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
                  // Semantic --danger-soft / --danger-fg pair passes WCAG AA in both
                  // themes — the previous `--color-danger/15` mix dropped to 3.4:1
                  // on the light surface (a11y-audit #5).
                  <span
                    key={flag}
                    className={[
                      "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
                      RISK_FLAG_TONE[flag] === "warn"
                        ? "bg-[var(--danger-soft)] text-[var(--danger-fg)]"
                        : "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
                    ].join(" ")}
                  >
                    {RISK_FLAG_TONE[flag] === "warn" && (
                      <AlertTriangle className="size-3" aria-hidden />
                    )}
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
              className="inline-flex items-center gap-2 rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm hover:bg-[var(--bg-muted)]"
            >
              <Send className="size-4" />
              Telegram
              <ArrowUpRight className="size-3.5 text-[var(--text-secondary)]" />
            </a>
          )}
          <Link
            to={`/wallet?user=${u.id}`}
            className="inline-flex items-center gap-2 rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm hover:bg-[var(--bg-muted)]"
          >
            <Wallet className="size-4" />
            Кошелёк
          </Link>
          <Link
            to={`/audit?target_id=${u.id}`}
            className="inline-flex items-center gap-2 rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm hover:bg-[var(--bg-muted)]"
          >
            <Receipt className="size-4" />
            Аудит
          </Link>
        </div>
      </div>

      {/* Roles + admin toggle. Lives inside the header so it stays close to
          the operator's other identity actions (Telegram / Wallet / Audit)
          without crowding the same row. */}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--border-subtle)] pt-4">
        <div className="flex items-center gap-3">
          <ShieldCheck
            className={isAdmin ? "size-4 text-[var(--warning)]" : "size-4 text-[var(--text-secondary)]"}
            aria-hidden
          />
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium">Роли:</span>
            {u.roles.length === 0 ? (
              <span className="text-xs text-[var(--text-secondary)]">user</span>
            ) : (
              u.roles.map((r) => (
                <span
                  key={r}
                  className={[
                    "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase",
                    r === "admin"
                      ? "bg-[var(--warning-soft)] text-[var(--warning-fg)]"
                      : "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
                  ].join(" ")}
                >
                  {r}
                </span>
              ))
            )}
          </div>
        </div>
        <Button
          size="sm"
          variant={isAdmin ? "danger" : "primary"}
          disabled={rolePending}
          onClick={onToggleAdmin}
        >
          {rolePending
            ? "Сохраняем…"
            : isAdmin
              ? "Снять админа"
              : "Выдать админа"}
        </Button>
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
    ? "text-[var(--accent)]"
    : tone === "warn"
      ? "text-[var(--danger)]"
      : tone === "success"
        ? "text-[var(--success-fg)]"
        : tone === "muted"
          ? "text-[var(--text-secondary)]"
          : "text-[var(--text-primary)]";
  return (
    <article className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4">
      <div className="text-xs uppercase tracking-wide text-[var(--text-secondary)]">{label}</div>
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
          <span className="text-[var(--text-secondary)]">—</span>
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
          <span className="text-[var(--danger)]">{t.last_error}</span>
        ) : (
          <span className="text-[var(--text-secondary)]">—</span>
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
        <p className="text-sm text-[var(--text-secondary)]">Аккаунтов кошелька нет.</p>
      ) : (
        <ul className="space-y-1.5">
          {balances.map((b) => (
            <li
              key={b.account_id}
              className="flex items-center justify-between rounded-md border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] px-3 py-2 text-sm"
            >
              <span className="text-[var(--text-secondary)]">{b.kind}</span>
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
        <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
          {title}
        </h2>
        <span
          className={[
            "text-xs",
            tone === "warn" && count > 0
              ? "text-[var(--danger)]"
              : "text-[var(--text-secondary)]",
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

function formatApiError(err: ApiError): string {
  const body = err.body as { detail?: string } | null;
  return body?.detail ?? err.message;
}
