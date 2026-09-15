import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Boxes,
  CheckCircle2,
  CircleDollarSign,
  Clock,
  CreditCard,
  Package,
  Receipt,
  RotateCcw,
  Truck,
  Users,
} from "lucide-react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/Badge";
import { Delta } from "@/components/Delta";
import { useAuthStore } from "@/features/auth/authStore";
import { type OrderStatus, STATUS_TONE } from "@/features/orders/types";
import { apiGet } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { qk } from "@/lib/queryKeys";

interface DashboardOut {
  generated_at: string;
  window_hours: number;
  orders_in_window: number;
  orders_delivered_in_window: number;
  orders_failed_in_window: number;
  revenue_in_window: { currency: string; amount: string }[];
  /** Optional on purpose: the admin ships separately from the API, so a
   *  bundle can reach a deployment that predates this field. Rendering must
   *  degrade to "no margin line", never take the whole dashboard down. */
  margin_in_window?: { amount_usd: string; pct: number; unknown_units: number };
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
  /** Optional for the same reason `margin_in_window` is: the admin bundle
   *  ships separately from the API, so a deploy skew must degrade to "no
   *  comparison" rather than take the overview down. */
  totals?: DashboardTotals;
  /** The window of equal length immediately before. Absent when nothing
   *  happened in it — a shop's first day has no yesterday. */
  previous?: DashboardTotals | null;
  channels_in_window?: { channel: string; orders: number; revenue_usd: string }[];
}

interface DashboardTotals {
  orders: number;
  delivered: number;
  failed: number;
  revenue_usd: string;
  margin_usd: string;
  refunded_usd: string;
}

/**
 * Dashboard-only wording for order statuses, kept separate from the orders
 * list's `STATUS_LABEL` on purpose: this is a tally ("Доставлено — 2"), so the
 * labels are neuter/plural, while a single order's badge reads "Доставлен".
 *
 * Typed against `OrderStatus` rather than `string` so it cannot drift from the
 * backend again — a status added to the union stops compiling here until it
 * gets wording, which is what let `failed` render as raw English. Tones carry
 * no grammar, so those are the shared map, not a third copy.
 */
const STATUS_LABEL: Record<OrderStatus, string> = {
  pending_payment: "Ждут оплаты",
  paid: "Оплачено",
  fulfilling: "В работе",
  fulfilled: "Готово",
  delivered: "Доставлено",
  failed: "Проблемные",
  cancelled: "Отменено",
  expired: "Истекло",
  refunded: "Возврат",
  partially_refunded: "Частичный возврат",
};

/** The breakdown arrives as a bare string from the API, so a status the union
 *  doesn't know about is possible at runtime even though the maps are
 *  exhaustive at compile time. Both casts widen rather than narrow — indexing
 *  a finite-key `Record` is typed as always-present, which would make the
 *  fallbacks below look dead while still being the thing that keeps an
 *  unrecognised status readable. */
type Lookup = Record<string, string | undefined>;

function statusLabel(status: string): string {
  return (STATUS_LABEL as Lookup)[status] ?? status;
}

function statusTone(status: string): string {
  return (STATUS_TONE as Lookup)[status] ?? "bg-[var(--bg-muted)] text-[var(--text-secondary)]";
}

export function DashboardPage() {
  const me = useAuthStore((s) => s.me);
  const q = useQuery<DashboardOut>({
    queryKey: qk.dashboard(24),
    queryFn: () => apiGet<DashboardOut>("/api/v1/admin/stats/dashboard?window_hours=24"),
    refetchInterval: 30_000,
  });

  const d = q.data;

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Привет, {me?.display_name ?? "админ"} 👋</h1>
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

      {q.isError && <p className="text-sm text-[var(--danger)]">Не удалось загрузить метрики.</p>}

      <section className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Kpi
          icon={Receipt}
          label="Заказы (24ч)"
          value={d?.orders_in_window ?? 0}
          accent
          delta={movement(d, (t) => t.orders)}
          sparkline={d?.orders_last_7_days.map((b) => b.count) ?? []}
        />
        <Kpi
          icon={CheckCircle2}
          label="Доставлено"
          value={d?.orders_delivered_in_window ?? 0}
          tone="success"
          delta={movement(d, (t) => t.delivered)}
        />
        <Kpi
          icon={AlertTriangle}
          label="Отменено / истекло"
          value={d?.orders_failed_in_window ?? 0}
          tone={(d?.orders_failed_in_window ?? 0) > 0 ? "warn" : "muted"}
          delta={movement(d, (t) => t.failed, true)}
        />
        <Kpi
          icon={CircleDollarSign}
          label="Выручка"
          // The USD equivalent, not the per-currency list: three currencies
          // cannot be compared with yesterday's three, and a movement needs
          // one number. What was actually charged is the line below.
          value={d?.totals ? formatMoney(d.totals.revenue_usd, "USD") : revenueFallback(d)}
          accent
          delta={movement(d, (t) => Number(t.revenue_usd))}
          sub={chargedLine(d)}
          hint={marginHint(d?.margin_in_window)}
          sparkline={d?.orders_last_7_days.map((b) => Number.parseFloat(b.revenue_usd) || 0) ?? []}
        />
        {/* Gross revenue above does not net refunds out, so without this card
            the screen cannot say a good morning was undone by an afternoon of
            them. Up is bad here, so the chip's colours are flipped. */}
        <Kpi
          icon={RotateCcw}
          label="Возвраты"
          value={d?.totals ? formatMoney(d.totals.refunded_usd, "USD") : "—"}
          tone={Number(d?.totals?.refunded_usd ?? 0) > 0 ? "warn" : "muted"}
          delta={movement(d, (t) => Number(t.refunded_usd), true)}
        />
      </section>

      <ChannelStrip channels={d?.channels_in_window ?? []} />

      <AlertsBlock
        stuck={d?.stuck_payments ?? 0}
        pendingOrders={d?.pending_orders ?? 0}
        inFlight={d?.in_flight_tasks ?? 0}
      />

      <section className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <article className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
          <header className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">Заказы за 7 дней</h2>
            <span className="flex items-baseline gap-3 text-xs text-[var(--text-secondary)]">
              {d?.orders_last_7_days.reduce((s, b) => s + b.count, 0) ?? 0} всего
              <Link to="/analytics" className="hover:underline">
                аналитика →
              </Link>
            </span>
          </header>
          {d ? (
            <DayBars buckets={d.orders_last_7_days} />
          ) : (
            <div className="h-32 animate-pulse rounded bg-[var(--bg-muted)]" />
          )}
        </article>

        <article className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
          <header className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold">Статусы за 24ч</h2>
            <Link to="/orders" className="text-xs text-[var(--text-secondary)] hover:underline">
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
                  <Badge tone={statusTone(s.status)} dot>
                    {statusLabel(s.status)}
                  </Badge>
                  <span className="font-mono text-sm">{s.count}</span>
                </li>
              ))}
            </ul>
          )}
        </article>
      </section>

      <section className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
        <header className="mb-3 flex items-baseline justify-between">
          <div className="flex items-center gap-2">
            <Boxes className="size-4 text-[var(--text-secondary)]" />
            <h2 className="text-sm font-semibold">Склад</h2>
          </div>
          <Link to="/inventory" className="text-xs text-[var(--text-secondary)] hover:underline">
            открыть склад →
          </Link>
        </header>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <MiniStat label="Доступно" value={d?.inventory.available ?? 0} tone="success" />
          <MiniStat label="Резерв" value={d?.inventory.reserved ?? 0} />
          <MiniStat label="Выдано" value={d?.inventory.issued ?? 0} />
          <MiniStat label="Воид" value={d?.inventory.voided ?? 0} tone="muted" />
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

/**
 * The margin line under the revenue figure.
 *
 * Cost is recorded in USD, so the percentage is what lets an operator read the
 * two as one thought. Uncosted units are named rather than folded in: the
 * figure describes part of the window's sales, and a card that does not say so
 * is read as if it described all of them.
 */
function marginHint(
  m: { amount_usd: string; pct: number; unknown_units: number } | undefined,
): string | undefined {
  if (!m) return undefined;
  const base = `Маржа ${formatMoney(m.amount_usd, "USD")} · ${m.pct.toFixed(1)}%`;
  return m.unknown_units > 0 ? `${base} · без себестоимости: ${m.unknown_units} шт.` : base;
}

/** What was actually charged, per currency — the truth under the USD headline.
 *  Its own line rather than folded into the margin hint: they are two separate
 *  facts, and one long run-on is read as neither. */
function chargedLine(d: DashboardOut | undefined): string | undefined {
  // Only under a USD headline. Against an API with no `totals` this list *is*
  // the headline, and printing it twice on one card is worse than not at all.
  if (!d?.totals || d.revenue_in_window.length === 0) return undefined;
  return d.revenue_in_window.map((r) => formatMoney(r.amount, r.currency)).join(" · ");
}

/** The old per-currency headline, for a bundle talking to an API that predates
 *  `totals`. Degrading to "no USD figure" beats rendering `$NaN`. */
function revenueFallback(d: DashboardOut | undefined): string {
  if (!d || d.revenue_in_window.length === 0) return "—";
  return d.revenue_in_window.map((r) => formatMoney(r.amount, r.currency)).join(" · ");
}

/** This window's figure and the previous window's, or `undefined` when there
 *  is no previous window to compare against. */
function movement(
  d: DashboardOut | undefined,
  pick: (t: DashboardTotals) => number,
  inverted = false,
): { now: number; was: number; inverted: boolean } | undefined {
  if (!d?.totals || !d.previous) return undefined;
  return { now: pick(d.totals), was: pick(d.previous), inverted };
}

/**
 * Retail and B2B, side by side.
 *
 * "43 заказа" does not say whether the wholesale side moved at all, and it is
 * the half that moves in steps of one. Hidden entirely until the API sends the
 * rows, so an older deployment shows the screen it always did.
 */
function ChannelStrip({
  channels,
}: {
  channels: { channel: string; orders: number; revenue_usd: string }[];
}) {
  if (channels.length === 0) return null;
  const label = (c: string) => (c === "b2b" ? "B2B" : "Розница");
  return (
    <section className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border bg-[var(--bg-surface)] px-4 py-3 text-sm shadow-[var(--shadow-sm)]">
      <span className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
        <Users className="size-4" aria-hidden />
        Каналы за 24ч
      </span>
      {channels.map((c) => (
        <span key={c.channel} className="flex items-baseline gap-2">
          <span className="text-[var(--text-secondary)]">{label(c.channel)}</span>
          <span className="font-semibold">{c.orders}</span>
          <span className="text-[var(--text-secondary)]">
            · {formatMoney(c.revenue_usd, "USD")}
          </span>
        </span>
      ))}
      <Link
        to="/analytics"
        className="ml-auto text-xs text-[var(--text-secondary)] hover:underline"
      >
        разбор по каналам →
      </Link>
    </section>
  );
}

function Kpi({
  icon: Icon,
  label,
  value,
  accent,
  tone,
  hint,
  sub,
  delta,
  sparkline,
}: {
  icon: typeof Receipt;
  label: string;
  value: number | string;
  accent?: boolean;
  tone?: "warn" | "success" | "muted";
  /** Secondary line under the value, for a figure that qualifies it. */
  hint?: string | undefined;
  /** A second such line, for a card carrying two of them. */
  sub?: string | undefined;
  /** This figure against the previous window's. `undefined` draws nothing,
   *  which is what a shop with no yesterday deserves. */
  delta?: { now: number; was: number; inverted: boolean } | undefined;
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
    <article className="rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
          {label}
        </span>
        <span className={`grid size-8 place-items-center rounded-md ${tileCls}`}>
          <Icon className="size-4" aria-hidden />
        </span>
      </div>
      <div className={`mt-3 text-2xl font-semibold ${valueCls}`}>{value}</div>
      {delta && (
        <div className="mt-1 text-xs">
          <Delta now={delta.now} was={delta.was} inverted={delta.inverted} />
          <span className="ml-1.5 text-[var(--text-secondary)]">к прошлым 24ч</span>
        </div>
      )}
      {sub && <div className="mt-1 text-xs text-[var(--text-secondary)]">{sub}</div>}
      {hint && <div className="mt-1 text-xs text-[var(--text-secondary)]">{hint}</div>}
      {sparkline && sparkline.length > 0 && <MiniSparkline values={sparkline} />}
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
        "rounded-lg border bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)] transition-colors",
        clickable ? "hover:bg-[var(--bg-muted)]/60 hover:border-[var(--color-fg)]/20" : "",
      ].join(" ")}
      style={
        tone === "warn" && value > 0
          ? {
              borderColor: "color-mix(in oklab, var(--color-danger) 50%, var(--border-default))",
            }
          : undefined
      }
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon
            className={`size-4 ${
              tone === "warn" && value > 0 ? "text-[var(--danger)]" : "text-[var(--text-secondary)]"
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
    <div className="rounded-md border bg-[var(--bg-surface)] p-3 shadow-[var(--shadow-sm)]">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-[var(--text-secondary)]">
        {Icon && <Icon className="size-3" />}
        {label}
      </div>
      <div className={`mt-1 text-xl font-semibold ${valueCls}`}>{value}</div>
    </div>
  );
}

function DayBars({ buckets }: { buckets: { date: string; count: number; revenue_usd: string }[] }) {
  const max = Math.max(...buckets.map((b) => b.count), 1);
  const half = Math.round(max / 2);
  return (
    <div className="relative">
      {/* Y-axis labels (max + 0). Mid-line label is the rounded half. */}
      <div className="pointer-events-none absolute inset-y-0 right-0 flex w-10 flex-col justify-between text-right font-mono text-[10px] text-[var(--text-tertiary)]">
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
            const heightPct = b.count === 0 ? 4 : Math.max(8, (b.count / max) * 100);
            const tooltip = `${formatDayLabel(b.date)}: ${b.count.toString()} заказов · ${formatMoney(b.revenue_usd, "USD")}`;
            return (
              <div
                key={b.date}
                title={tooltip}
                className="group flex flex-1 flex-col items-center gap-1"
              >
                <div
                  className="flex w-full items-end justify-center rounded-t font-mono text-[10px] transition-all group-hover:brightness-110"
                  style={{
                    height: `${heightPct.toString()}%`,
                    background:
                      b.count === 0
                        ? "var(--border-default)"
                        : "color-mix(in oklab, var(--accent) 75%, transparent)",
                    color: b.count === 0 ? "var(--text-secondary)" : "var(--text-on-accent)",
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
