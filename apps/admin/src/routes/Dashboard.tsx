import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  CircleDollarSign,
  Clock,
  CreditCard,
  Package,
  Receipt,
  Truck,
} from "lucide-react";

import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useAuthStore } from "@/features/auth/authStore";

interface DashboardOut {
  generated_at: string;
  window_hours: number;
  orders_in_window: number;
  orders_delivered_in_window: number;
  orders_failed_in_window: number;
  revenue_in_window: { currency: string; amount: string }[];
  status_breakdown: { status: string; count: number }[];
  in_flight_tasks: number;
  stuck_payments: number;
  pending_orders: number;
  inventory: {
    available: number;
    reserved: number;
    issued: number;
    voided: number;
    low_stock_skus: number;
  };
  orders_last_7_days: { date: string; count: number; revenue_usd: string }[];
}

const STATUS_LABEL: Record<string, string> = {
  pending_payment: "Ждут оплаты",
  paid: "Оплачено",
  fulfilling: "В работе",
  fulfilled: "Готово",
  delivered: "Доставлено",
  cancelled: "Отменено",
  expired: "Истекло",
  refunded: "Возврат",
};

const STATUS_TONE: Record<string, string> = {
  pending_payment: "bg-[var(--warning-soft)] text-[var(--warning-fg)]",
  paid: "bg-[var(--info-soft)] text-[var(--info-fg)]",
  fulfilling: "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]",
  fulfilled: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  delivered: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  cancelled: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  expired: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  refunded: "bg-[var(--danger-soft)] text-[var(--danger-fg)]",
};

export function DashboardPage() {
  const me = useAuthStore((s) => s.me);
  const q = useQuery<DashboardOut>({
    queryKey: qk.dashboard(24),
    queryFn: () =>
      apiGet<DashboardOut>("/api/v1/admin/stats/dashboard?window_hours=24"),
    refetchInterval: 30_000,
  });

  const d = q.data;

  return (
    <div className="space-y-6">
      <header className="flex items-baseline justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold">
            Привет, {me?.display_name ?? "админ"} 👋
          </h1>
          <p className="mt-1 text-sm text-[var(--text-secondary)]">
            Сводка за последние 24 часа. Обновляется автоматически каждые 30 сек.
          </p>
        </div>
        {d && (
          <span className="text-xs text-[var(--text-secondary)]">
            обновлено{" "}
            {new Date(d.generated_at).toLocaleTimeString("ru", {
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            })}
          </span>
        )}
      </header>

      {q.isError && (
        <p className="text-sm text-[var(--danger)]">
          Не удалось загрузить метрики.
        </p>
      )}

      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Kpi
          icon={Receipt}
          label="Заказы (24ч)"
          value={d?.orders_in_window ?? 0}
          accent
          sparkline={d?.orders_last_7_days.map((b) => b.count) ?? []}
        />
        <Kpi
          icon={CheckCircle2}
          label="Доставлено"
          value={d?.orders_delivered_in_window ?? 0}
          tone="success"
        />
        <Kpi
          icon={AlertTriangle}
          label="Отменено / истекло"
          value={d?.orders_failed_in_window ?? 0}
          tone={(d?.orders_failed_in_window ?? 0) > 0 ? "warn" : "muted"}
        />
        <Kpi
          icon={CircleDollarSign}
          label="Выручка"
          value={
            d && d.revenue_in_window.length > 0
              ? d.revenue_in_window
                  .map(
                    (r) =>
                      `${Number.parseFloat(r.amount).toFixed(2)} ${r.currency}`,
                  )
                  .join(" · ")
              : "—"
          }
          accent
          sparkline={
            d?.orders_last_7_days.map((b) =>
              Number.parseFloat(b.revenue_usd) || 0,
            ) ?? []
          }
        />
      </section>

      <AlertsBlock
        stuck={d?.stuck_payments ?? 0}
        pendingOrders={d?.pending_orders ?? 0}
        inFlight={d?.in_flight_tasks ?? 0}
      />

      <section className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <article className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4">
          <header className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">Заказы за 7 дней</h2>
            <span className="text-xs text-[var(--text-secondary)]">
              {d?.orders_last_7_days.reduce((s, b) => s + b.count, 0) ?? 0}{" "}
              всего
            </span>
          </header>
          {d ? (
            <DayBars buckets={d.orders_last_7_days} />
          ) : (
            <div className="h-32 animate-pulse rounded bg-[var(--bg-muted)]" />
          )}
        </article>

        <article className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4">
          <header className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">Статусы за 24ч</h2>
            <Link
              to="/orders"
              className="text-xs text-[var(--text-secondary)] hover:underline"
            >
              открыть заказы →
            </Link>
          </header>
          {d?.status_breakdown.length === 0 ? (
            <p className="text-sm text-[var(--text-secondary)]">За окно ничего нет.</p>
          ) : (
            <ul className="space-y-1.5">
              {(d?.status_breakdown ?? []).map((s) => (
                <li
                  key={s.status}
                  className="flex items-center justify-between rounded-md px-3 py-1.5"
                  style={{ background: "var(--bg-muted)" }}
                >
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      STATUS_TONE[s.status] ?? "bg-[var(--bg-muted)] text-[var(--text-secondary)]"
                    }`}
                  >
                    {STATUS_LABEL[s.status] ?? s.status}
                  </span>
                  <span className="font-mono text-sm">{s.count}</span>
                </li>
              ))}
            </ul>
          )}
        </article>
      </section>

      <section className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4">
        <header className="mb-3 flex items-baseline justify-between">
          <div className="flex items-center gap-2">
            <Boxes className="size-4 text-[var(--text-secondary)]" />
            <h2 className="text-sm font-semibold">Склад</h2>
          </div>
          <Link
            to="/inventory"
            className="text-xs text-[var(--text-secondary)] hover:underline"
          >
            открыть склад →
          </Link>
        </header>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <MiniStat
            label="Доступно"
            value={d?.inventory.available ?? 0}
            tone="success"
          />
          <MiniStat label="Резерв" value={d?.inventory.reserved ?? 0} />
          <MiniStat label="Выдано" value={d?.inventory.issued ?? 0} />
          <MiniStat
            label="Воид"
            value={d?.inventory.voided ?? 0}
            tone="muted"
          />
          <MiniStat
            icon={Package}
            label="SKU без запаса"
            value={d?.inventory.low_stock_skus ?? 0}
            tone={(d?.inventory.low_stock_skus ?? 0) > 0 ? "warn" : "muted"}
          />
        </div>
      </section>
    </div>
  );
}

function Kpi({
  icon: Icon,
  label,
  value,
  accent,
  tone,
  sparkline,
}: {
  icon: typeof Receipt;
  label: string;
  value: number | string;
  accent?: boolean;
  tone?: "warn" | "success" | "muted";
  /** Optional 7-day series rendered as a mini sparkline under the value. */
  sparkline?: number[];
}) {
  const valueCls = accent
    ? "text-[var(--accent)]"
    : tone === "warn"
      ? "text-[var(--danger)]"
      : tone === "success"
        ? "text-[var(--success-fg)]"
        : tone === "muted"
          ? "text-[var(--text-secondary)]"
          : "text-[var(--text-primary)]";
  // Each KPI gets a tinted square tile in the corner so the metric reads as a
  // small visual object instead of a flat label. The tile colour follows the
  // metric's tone so the eye can scan a row of KPIs by colour alone.
  const tileCls =
    tone === "warn"
      ? "bg-[var(--danger-soft)] text-[var(--danger-fg)]"
      : tone === "success"
        ? "bg-[var(--success-soft)] text-[var(--success-fg)]"
        : tone === "muted"
          ? "bg-[var(--bg-muted)] text-[var(--text-secondary)]"
          : "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]";
  return (
    <article className="rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4">
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
          {label}
        </span>
        <span className={`grid size-8 place-items-center rounded-md ${tileCls}`}>
          <Icon className="size-4" aria-hidden />
        </span>
      </div>
      <div className={`mt-3 text-2xl font-semibold ${valueCls}`}>{value}</div>
      {sparkline && sparkline.length > 0 && (
        <MiniSparkline values={sparkline} />
      )}
    </article>
  );
}

function MiniSparkline({ values }: { values: number[] }) {
  const max = Math.max(...values, 1);
  return (
    <div
      className="mt-3 flex h-6 items-end gap-[3px]"
      aria-hidden
      title={`Динамика за 7 дней: ${values.join(", ")}`}
    >
      {values.map((v, i) => {
        const ratio = v / max;
        return (
          <span
            key={i}
            className="flex-1 rounded-sm bg-[var(--accent)]"
            style={{
              height: `${Math.max(10, ratio * 100).toString()}%`,
              opacity: 0.35 + 0.65 * ratio,
            }}
          />
        );
      })}
    </div>
  );
}

/**
 * Combined alerts strip — when everything is at zero the screen turns into a
 * single calm "Очередей нет" line so the operator doesn't keep staring at three
 * identical grey-zero cards every shift. The moment any counter goes non-zero,
 * the expanded three-card layout returns and only the hot alerts get the warn
 * tone.
 */
function AlertsBlock({
  stuck,
  pendingOrders,
  inFlight,
}: {
  stuck: number;
  pendingOrders: number;
  inFlight: number;
}) {
  const total = stuck + pendingOrders + inFlight;
  if (total === 0) {
    return (
      <section className="flex items-center gap-3 rounded-lg border bg-[var(--success-soft)] px-4 py-3 text-sm text-[var(--success-fg)] shadow-[var(--shadow-sm)]">
        <CheckCircle2 className="size-4" aria-hidden />
        <span>
          <strong className="font-semibold">Всё чисто.</strong> Очередей нет.
        </span>
      </section>
    );
  }
  return (
    <section className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <AlertCard
        icon={CreditCard}
        label="Висящие платежи"
        hint="pending дольше порога — открыть триаж"
        value={stuck}
        tone={stuck > 0 ? "warn" : "muted"}
        to="/payments/triage?tab=stuck"
      />
      <AlertCard
        icon={Clock}
        label="Ждут оплаты"
        hint="заказы старше 5 минут без платежа"
        value={pendingOrders}
        tone={pendingOrders > 0 ? "warn" : "muted"}
        to="/orders?status=pending_payment"
      />
      <AlertCard
        icon={Truck}
        label="В работе"
        hint="Висяки > 30 мин — открыть Stuck-таб"
        value={inFlight}
        tone={inFlight > 0 ? "warn" : "muted"}
        to="/fulfillment?tab=stuck"
      />
    </section>
  );
}

function AlertCard({
  icon: Icon,
  label,
  hint,
  value,
  tone = "default",
  to,
}: {
  icon: typeof CreditCard;
  label: string;
  hint: string;
  value: number;
  tone?: "warn" | "muted" | "default";
  to?: string;
}) {
  const clickable = Boolean(to);
  const inner = (
    <article
      className={[
        "rounded-lg border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-4 transition-colors",
        clickable ? "hover:bg-[var(--bg-muted)]/60 hover:border-[var(--color-fg)]/20" : "",
      ].join(" ")}
      style={
        tone === "warn" && value > 0
          ? {
              borderColor:
                "color-mix(in oklab, var(--color-danger) 50%, var(--border-default))",
            }
          : undefined
      }
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon
            className={`size-4 ${
              tone === "warn" && value > 0
                ? "text-[var(--danger)]"
                : "text-[var(--text-secondary)]"
            }`}
          />
          <span className="text-sm font-semibold">{label}</span>
        </div>
        <span
          className={`text-xl font-bold ${
            tone === "warn" && value > 0 ? "text-[var(--danger)]" : ""
          }`}
        >
          {value}
        </span>
      </div>
      <p className="mt-1 text-xs text-[var(--text-secondary)]">{hint}</p>
    </article>
  );
  return to ? (
    <Link to={to} aria-label={`${label}: ${value.toString()}`}>
      {inner}
    </Link>
  ) : (
    inner
  );
}

function MiniStat({
  icon: Icon,
  label,
  value,
  tone = "default",
}: {
  icon?: typeof Package;
  label: string;
  value: number;
  tone?: "warn" | "success" | "muted" | "default";
}) {
  const valueCls =
    tone === "warn"
      ? "text-[var(--danger)]"
      : tone === "success"
        ? "text-[var(--success-fg)]"
        : tone === "muted"
          ? "text-[var(--text-secondary)]"
          : "text-[var(--text-primary)]";
  return (
    <div className="rounded-md border bg-[var(--bg-surface)] shadow-[var(--shadow-sm)] p-3">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">
        {Icon && <Icon className="size-3" />}
        {label}
      </div>
      <div className={`mt-1 text-xl font-semibold ${valueCls}`}>{value}</div>
    </div>
  );
}

function DayBars({
  buckets,
}: {
  buckets: { date: string; count: number; revenue_usd: string }[];
}) {
  const max = Math.max(...buckets.map((b) => b.count), 1);
  const half = Math.round(max / 2);
  return (
    <div className="relative">
      {/* Y-axis labels (max + 0). Mid-line label is the rounded half. */}
      <div className="pointer-events-none absolute inset-y-0 right-0 flex w-10 flex-col justify-between text-right text-[10px] font-mono text-[var(--text-tertiary)]">
        <span>{max}</span>
        <span>{half}</span>
        <span>0</span>
      </div>
      {/* Dashed gridline at the half-way mark — gives the bars a reference
          point so the magnitudes read without squinting. */}
      <div className="relative h-32">
        <div className="pointer-events-none absolute inset-x-0 top-1/2 border-t border-dashed border-[var(--border-default)]" />
        <div className="relative flex h-full items-end gap-2 pr-12">
          {buckets.map((b) => {
            const heightPct =
              b.count === 0 ? 4 : Math.max(8, (b.count / max) * 100);
            const revenue = Number.parseFloat(b.revenue_usd) || 0;
            const tooltip = `${formatDayLabel(b.date)}: ${b.count.toString()} заказов · ${revenue.toFixed(2)} USD`;
            return (
              <div
                key={b.date}
                title={tooltip}
                className="group flex flex-1 flex-col items-center gap-1"
              >
                <div
                  className="w-full rounded-t flex items-end justify-center text-[10px] font-mono transition-all group-hover:brightness-110"
                  style={{
                    height: `${heightPct.toString()}%`,
                    background:
                      b.count === 0
                        ? "var(--border-default)"
                        : "color-mix(in oklab, var(--accent) 75%, transparent)",
                    color:
                      b.count === 0
                        ? "var(--text-secondary)"
                        : "var(--text-on-accent)",
                  }}
                >
                  {b.count > 0 && <span className="pb-1">{b.count}</span>}
                </div>
                <span className="text-[10px] text-[var(--text-secondary)]">
                  {b.date.slice(5).replace("-", "/")}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function formatDayLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("ru", { day: "2-digit", month: "short" });
}
