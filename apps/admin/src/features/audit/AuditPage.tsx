import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  CreditCard,
  Filter,
  Radio,
  Receipt,
  RotateCcw,
  Search,
  ShieldCheck,
  Truck,
  Wallet,
} from "lucide-react";

import { Button, Input } from "@yupay/ui";

import { PageHeader } from "@/components/PageHeader";
import { apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useSearchParamsState } from "@/lib/useSearchParamsState";

type Source =
  | "order_event"
  | "payment_attempt"
  | "payment_webhook"
  | "fulfillment_attempt"
  | "wallet_transaction";

interface AuditEvent {
  id: string;
  ts: string;
  source: Source;
  kind: string;
  actor: string | null;
  target_id: string | null;
  target_kind: string | null;
  payload: Record<string, unknown>;
}

interface AuditListOut {
  items: AuditEvent[];
}

const SOURCES: { key: Source; label: string; icon: typeof Receipt; tone: string }[] = [
  { key: "order_event", label: "Заказы", icon: Receipt, tone: "text-violet-600" },
  { key: "payment_attempt", label: "Платежи", icon: CreditCard, tone: "text-sky-600" },
  { key: "payment_webhook", label: "Webhooks", icon: Radio, tone: "text-amber-600" },
  { key: "fulfillment_attempt", label: "Fulfilment", icon: Truck, tone: "text-emerald-600" },
  { key: "wallet_transaction", label: "Кошелёк", icon: Wallet, tone: "text-rose-600" },
];

const SOURCE_META: Record<
  Source,
  { label: string; icon: typeof Receipt; tone: string }
> = SOURCES.reduce(
  (acc, s) => {
    acc[s.key] = { label: s.label, icon: s.icon, tone: s.tone };
    return acc;
  },
  {} as Record<Source, { label: string; icon: typeof Receipt; tone: string }>,
);

export function AuditPage() {
  const [enabled, setEnabled] = useState<Record<Source, boolean>>(() =>
    Object.fromEntries(SOURCES.map((s) => [s.key, true])) as Record<Source, boolean>,
  );
  const [actor, setActor] = useState("");
  const [target, setTarget] = useState("");
  const [limit, setLimit] = useState(100);
  const [expanded, setExpanded] = useState<string | null>(null);
  // URL-bound so the sidebar's "Действия админов" link can pre-filter the feed
  // and the operator can share an admin-only view.
  const [adminOnlyParam, setAdminOnlyParam] = useSearchParamsState<string>(
    "admin_only",
    "",
  );
  const adminOnly = adminOnlyParam === "true";

  const sources = SOURCES.filter((s) => enabled[s.key]).map((s) => s.key);

  const q = useQuery<AuditListOut>({
    queryKey: [
      ...qk.audit({
        sources,
        actor: actor.trim() || null,
        target: target.trim() || null,
      }),
      "admin_only",
      adminOnly,
    ],
    queryFn: () => {
      const params = new URLSearchParams();
      sources.forEach((s) => params.append("sources", s));
      if (actor.trim()) params.set("actor", actor.trim());
      if (target.trim()) params.set("target_id", target.trim());
      if (adminOnly) params.set("admin_only", "true");
      params.set("limit", String(limit));
      return apiGet<AuditListOut>(`/api/v1/admin/audit?${params.toString()}`);
    },
    refetchInterval: 15_000,
  });

  const rows = q.data?.items ?? [];

  const stats = useMemo(() => {
    const bySource: Partial<Record<Source, number>> = {};
    let actors = new Set<string>();
    for (const e of rows) {
      bySource[e.source] = (bySource[e.source] ?? 0) + 1;
      if (e.actor) actors.add(e.actor);
    }
    return { bySource, actorsCount: actors.size };
  }, [rows]);

  const hourlyHistogram = useMemo(() => buildHistogram(rows), [rows]);

  return (
    <div>
      <PageHeader
        title={adminOnly ? "Действия админов" : "Activity / Audit log"}
        description={
          adminOnly
            ? "События с actor LIKE 'admin:%' — что админы делали в системе."
            : "Сведённый поток событий: заказы, платежи, webhooks, фулфилмент, кошелёк."
        }
        actions={
          <>
            <button
              type="button"
              onClick={() => { setAdminOnlyParam(adminOnly ? "" : "true"); }}
              className={[
                "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors",
                adminOnly
                  ? "border-[--color-brand] bg-[--color-brand]/10 text-[--color-fg]"
                  : "border-[--color-border] text-[--color-muted] hover:bg-[--color-subtle]",
              ].join(" ")}
              aria-pressed={adminOnly}
            >
              <ShieldCheck className="size-4" />
              Только админы
            </button>
            <Button
              type="button"
              variant="ghost"
              onClick={() => q.refetch()}
              disabled={q.isFetching}
            >
              <RotateCcw
                className={`size-4 ${q.isFetching ? "animate-spin" : ""}`}
              />
              Обновить
            </Button>
          </>
        }
      />

      <section className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3">
        <StatCard label="События" value={rows.length} accent />
        <StatCard label="Актёров" value={stats.actorsCount} />
        <StatCard
          label="Активность"
          render={
            hourlyHistogram.length === 0 ? null : (
              <Sparkline values={hourlyHistogram} />
            )
          }
        />
      </section>

      <section className="mb-5 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <Filter className="size-4 text-[--color-muted]" />
          {SOURCES.map((s) => {
            const on = enabled[s.key];
            const Icon = s.icon;
            return (
              <button
                key={s.key}
                type="button"
                onClick={() =>
                  setEnabled((prev) => ({ ...prev, [s.key]: !prev[s.key] }))
                }
                className="inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium transition-all"
                style={{
                  background: on ? "var(--color-subtle)" : "transparent",
                  color: on ? undefined : "var(--color-muted)",
                  border: on
                    ? "1.5px solid var(--color-border)"
                    : "1.5px solid var(--color-border)",
                  opacity: on ? 1 : 0.55,
                }}
              >
                <Icon className={`size-3.5 ${on ? s.tone : ""}`} />
                {s.label}
                <span
                  className={`ml-1 text-[10px] font-bold ${
                    on ? "" : "opacity-60"
                  }`}
                >
                  {stats.bySource[s.key] ?? 0}
                </span>
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap gap-2">
          <div className="relative flex-1 min-w-48">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[--color-muted]" />
            <Input
              value={actor}
              onChange={(e) => setActor(e.target.value)}
              placeholder="Фильтр по actor (admin:<id>, payments, fulfillment)…"
              className="pl-9 text-xs"
            />
          </div>
          <div className="relative flex-1 min-w-48">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[--color-muted]" />
            <Input
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              placeholder="Фильтр по target_id (order/payment/task UUID)…"
              className="pl-9 text-xs"
            />
          </div>
          <select
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
            className="h-10 rounded-md border border-[--color-border] bg-[--color-bg] px-3 text-sm"
          >
            <option value={50}>50 событий</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
            <option value={500}>500</option>
          </select>
        </div>
      </section>

      {q.isError && (
        <p className="text-sm text-[--color-danger]">Ошибка загрузки.</p>
      )}

      <div className="space-y-1">
        {rows.length === 0 && !q.isLoading && (
          <div className="rounded-lg border border-dashed border-[--color-border] p-10 text-center text-sm text-[--color-muted]">
            События не найдены под текущие фильтры.
          </div>
        )}
        {rows.map((e, i) => (
          <TimelineRow
            key={e.id + i}
            event={e}
            expanded={expanded === e.id}
            onToggle={() => setExpanded(expanded === e.id ? null : e.id)}
          />
        ))}
      </div>

      <p className="mt-3 text-xs text-[--color-muted]">
        Источники: ``order_events``, ``payment_attempts``,
        ``payment_webhooks``, ``fulfillment_attempts``, ``wallet_transactions``.
        Сортировка по timestamp. Авто-обновление каждые 15 сек.
      </p>
    </div>
  );
}

function TimelineRow({
  event,
  expanded,
  onToggle,
}: {
  event: AuditEvent;
  expanded: boolean;
  onToggle: () => void;
}) {
  const meta = SOURCE_META[event.source];
  const Icon = meta.icon;
  const ok = !event.kind.endsWith(".error") && !event.kind.endsWith(".rejected");
  const isError = event.kind.endsWith(".error");
  const isRejected = event.kind.endsWith(".rejected");
  const StateIcon = isError || isRejected ? AlertTriangle : ok ? CheckCircle2 : Activity;

  return (
    <article
      className="rounded-lg border bg-[--color-bg] transition-colors hover:bg-[--color-subtle]/30"
    >
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-start gap-3 p-3 text-left"
      >
        <span
          className="mt-0.5 inline-flex size-7 flex-shrink-0 items-center justify-center rounded-full"
          style={{
            background: "var(--color-subtle)",
          }}
          title={meta.label}
        >
          <Icon className={`size-3.5 ${meta.tone}`} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1 text-sm">
            <code className="font-medium">{event.kind}</code>
            <StateIcon
              className={`size-3 ${
                isError || isRejected
                  ? "text-rose-600"
                  : ok
                    ? "text-emerald-600"
                    : "text-[--color-muted]"
              }`}
            />
            <span className="text-xs text-[--color-muted]">{formatTime(event.ts)}</span>
          </div>
          <div className="mt-0.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs text-[--color-muted]">
            {event.actor && (
              <span>
                actor <code className="text-[--color-fg]">{event.actor}</code>
              </span>
            )}
            {event.target_id && event.target_kind && (
              <span>
                {event.target_kind}{" "}
                <TargetLink kind={event.target_kind} id={event.target_id} />
              </span>
            )}
          </div>
        </div>
      </button>
      {expanded && Object.keys(event.payload).length > 0 && (
        <pre className="mx-3 mb-3 whitespace-pre-wrap break-all rounded border bg-[--color-subtle] p-3 text-[10px] leading-relaxed text-[--color-muted]">
          {JSON.stringify(event.payload, null, 2)}
        </pre>
      )}
    </article>
  );
}

function TargetLink({ kind, id }: { kind: string; id: string }) {
  const shortened = id.length > 18 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id;
  if (kind === "order") {
    return (
      <Link
        to={`/orders/${id}`}
        className="font-mono text-[--color-brand] hover:underline"
        onClick={(e) => e.stopPropagation()}
      >
        {shortened}
      </Link>
    );
  }
  return <code className="text-[--color-fg]">{shortened}</code>;
}

function StatCard({
  label,
  value,
  accent,
  render,
}: {
  label: string;
  value?: number;
  accent?: boolean;
  render?: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border bg-[--color-bg] p-4">
      {render ?? (
        <div
          className={`text-2xl font-semibold ${
            accent ? "text-[--color-brand]" : "text-[--color-fg]"
          }`}
        >
          {value ?? 0}
        </div>
      )}
      <div className="mt-1 text-xs uppercase tracking-wide text-[--color-muted]">
        {label}
      </div>
    </div>
  );
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length === 0) return null;
  const max = Math.max(...values, 1);
  return (
    <div className="flex h-8 items-end gap-0.5">
      {values.map((v, i) => (
        <span
          key={i}
          className="flex-1 rounded-sm"
          style={{
            height: `${Math.max(8, (v / max) * 100)}%`,
            background:
              v === 0
                ? "var(--color-border)"
                : "color-mix(in oklab, var(--color-brand) 70%, transparent)",
          }}
          title={`${v} событий`}
        />
      ))}
    </div>
  );
}

function buildHistogram(rows: AuditEvent[]): number[] {
  if (rows.length === 0) return [];
  // Compute 24 buckets covering the last 24 hours, anchored to the most-recent
  // event so it always fills the right edge.
  const newest = new Date(rows[0]!.ts).getTime();
  const bucketSize = 60 * 60 * 1000; // 1 hour
  const buckets = new Array(24).fill(0);
  const oldest = newest - 24 * bucketSize;
  for (const r of rows) {
    const t = new Date(r.ts).getTime();
    if (t < oldest) continue;
    const idx = Math.min(
      23,
      Math.max(0, Math.floor((t - oldest) / bucketSize)),
    );
    buckets[idx] += 1;
  }
  return buckets;
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = Date.now();
  const diff = now - d.getTime();
  if (diff < 60_000) return "сейчас";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} мин назад`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} ч назад`;
  return d.toLocaleString("ru", {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}
