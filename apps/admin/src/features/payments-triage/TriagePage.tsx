/**
 * Payments Triage — `/payments/triage`.
 *
 * Two focused buckets, both fed by a single aggregate `GET /admin/payments/triage`:
 *   - Stuck pending — payments that haven't moved past `pending` for longer than
 *     the chosen threshold (operator can pick 15 / 30 / 60 / 120 min).
 *   - Failed webhooks — incoming provider events that either failed signature
 *     verification or never got processed.
 *
 * Rows link straight to /orders/{id}; the user column (when present) jumps to
 * Customer 360. There are no bulk actions in this MVP — see ADR-0017 §"What we
 * don't do" for the rationale (force-cancel on a real-money payment is the kind
 * of thing that needs a separate review, not a checkbox).
 */

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, ShieldAlert } from "lucide-react";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { PaymentTriageOut, PaymentTriageRow, WebhookTriageRow } from "./types";

import { Badge } from "@/components/Badge";
import { CopyId } from "@/components/CopyId";
import { DataTable, type Column } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { Tabs, type TabDescriptor } from "@/components/Tabs";
import { UserRef } from "@/components/UserRef";
import { SaveSegmentButton } from "@/features/segments/SaveSegmentButton";
import { type ApiError, apiGet } from "@/lib/api";
import { formatMoney } from "@/lib/money";
import { qk } from "@/lib/queryKeys";
import { numberCodec, useSearchParamsState } from "@/lib/useSearchParamsState";
import { useAdminRefs } from "@/lib/useAdminRefs";
import { Select } from "@yupay/ui";

type TriageTab = "stuck" | "webhooks";

const VALID_TABS: ReadonlySet<TriageTab> = new Set<TriageTab>(["stuck", "webhooks"]);

const THRESHOLDS = [15, 30, 60, 120] as const;

export function TriagePage() {
  const navigate = useNavigate();
  const [rawTab, setTab] = useSearchParamsState("tab", "stuck");
  const tab: TriageTab = VALID_TABS.has(rawTab as TriageTab) ? (rawTab as TriageTab) : "stuck";
  const [threshold, setThreshold] = useSearchParamsState<number>("after", 30, numberCodec);

  const query = useQuery<PaymentTriageOut, ApiError>({
    queryKey: qk.paymentsTriage(threshold),
    queryFn: () =>
      apiGet<PaymentTriageOut>(
        `/api/v1/admin/payments/triage?stuck_after_minutes=${threshold.toString()}`,
      ),
    refetchInterval: 30_000,
  });

  const data = query.data;
  const stuckCount = data?.stuck_pending.length ?? 0;
  const webhookCount = data?.failed_webhooks.length ?? 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Триаж платежей"
        description="Что требует внимания финансов / тех-поддержки прямо сейчас."
        actions={<SaveSegmentButton />}
      />

      <Tabs<TriageTab>
        value={tab}
        onChange={setTab}
        ariaLabel="Вкладки триажа"
        tabs={[
          {
            id: "stuck",
            label: "Висящие платежи",
            badge: { count: stuckCount, tone: "warn" },
          } satisfies TabDescriptor<TriageTab>,
          {
            id: "webhooks",
            label: "Сбои webhooks",
            badge: { count: webhookCount, tone: "warn" },
          } satisfies TabDescriptor<TriageTab>,
        ]}
      />

      {tab === "stuck" && (
        <StuckSection
          threshold={threshold}
          onThresholdChange={setThreshold}
          rows={data?.stuck_pending ?? []}
          loading={query.isPending}
          error={query.isError}
          onOpenOrder={(orderId) => {
            void navigate(`/orders/${orderId}`);
          }}
        />
      )}

      {tab === "webhooks" && (
        <WebhookSection
          rows={data?.failed_webhooks ?? []}
          loading={query.isPending}
          error={query.isError}
        />
      )}
    </div>
  );
}

function StuckSection({
  threshold,
  onThresholdChange,
  rows,
  loading,
  error,
  onOpenOrder,
}: {
  threshold: number;
  onThresholdChange: (n: number) => void;
  rows: PaymentTriageRow[];
  loading: boolean;
  error: boolean;
  onOpenOrder: (orderId: string) => void;
}) {
  const totalsByCurrency = useMemo(() => {
    const sum: Record<string, number> = {};
    for (const r of rows) {
      const v = Number.parseFloat(r.amount);
      if (!Number.isFinite(v)) continue;
      sum[r.currency] = (sum[r.currency] ?? 0) + v;
    }
    return sum;
  }, [rows]);

  // Only this section has user ids; the webhook table has none.
  const refs = useAdminRefs(rows.map((p) => p.user_id));

  const columns: Column<PaymentTriageRow>[] = [
    {
      key: "payment",
      header: "Платёж",
      render: (p) => (
        <div className="flex flex-col font-mono text-xs">
          <CopyId value={p.id} />
          <span className="text-[var(--text-secondary)]">{p.provider}</span>
        </div>
      ),
      className: "w-32",
    },
    {
      key: "actor",
      header: "Клиент",
      render: (p) =>
        p.user_id ? (
          <UserRef id={p.user_id} data={refs.user(p.user_id)} className="text-xs" />
        ) : (
          <span className="text-xs text-[var(--text-secondary)]">{p.guest_email ?? "—"}</span>
        ),
    },
    {
      key: "amount",
      header: "Сумма",
      render: (p) => <span className="font-mono">{formatMoney(p.amount, p.currency)}</span>,
      className: "w-36 text-right",
    },
    {
      key: "waiting",
      header: "Ждёт",
      render: (p) => <SlaBadge minutes={p.waiting_minutes} />,
      className: "w-28",
      sortAccessor: (p) => p.waiting_minutes,
    },
    {
      key: "created",
      header: "Создан",
      render: (p) =>
        new Date(p.created_at).toLocaleString("ru", {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        }),
      className: "w-32",
    },
  ];

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-[var(--text-secondary)]">
          Платежи в статусе <code>pending</code> дольше выбранного порога.
        </p>
        <label className="flex items-center gap-2 text-sm">
          <span className="text-[var(--text-secondary)]">Порог:</span>
          <Select
            value={threshold.toString()}
            onChange={(e) => {
              onThresholdChange(Number(e.target.value));
            }}
            containerClassName="w-auto"
          >
            {THRESHOLDS.map((m) => (
              <option key={m} value={m.toString()}>
                ≥ {m.toString()} мин
              </option>
            ))}
          </Select>
        </label>
      </div>

      {Object.keys(totalsByCurrency).length > 0 && (
        <p className="text-xs text-[var(--text-secondary)]">
          Сумма в очереди:{" "}
          {Object.entries(totalsByCurrency)
            .map(([cur, v]) => formatMoney(v, cur))
            .join(" · ")}
        </p>
      )}

      {error && <p className="text-sm text-[var(--danger)]">Не удалось загрузить список.</p>}

      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(p) => p.id}
        empty={loading ? "Загрузка…" : "Висящих платежей нет."}
        onRowClick={(p) => {
          onOpenOrder(p.order_id);
        }}
      />
    </div>
  );
}

function WebhookSection({
  rows,
  loading,
  error,
}: {
  rows: WebhookTriageRow[];
  loading: boolean;
  error: boolean;
}) {
  const columns: Column<WebhookTriageRow>[] = [
    {
      key: "provider",
      header: "Провайдер",
      render: (w) => (
        <span className="rounded-md bg-[var(--bg-muted)] px-2 py-0.5 font-mono text-xs">
          {w.provider}
        </span>
      ),
      className: "w-28",
    },
    {
      key: "event",
      header: "Event ID",
      render: (w) => (
        <code className="text-xs">
          {w.external_event_id.length > 18
            ? `${w.external_event_id.slice(0, 18)}…`
            : w.external_event_id}
        </code>
      ),
    },
    {
      key: "sig",
      header: "Подпись",
      render: (w) =>
        w.signature_ok ? (
          <span className="inline-flex items-center gap-1 text-xs text-[var(--success-fg)]">
            <CheckCircle2 className="size-3" />
            OK
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 text-xs text-[var(--danger-fg)]">
            <ShieldAlert className="size-3" />
            rejected
          </span>
        ),
      className: "w-28",
    },
    {
      key: "received",
      header: "Получен",
      render: (w) =>
        new Date(w.received_at).toLocaleString("ru", {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        }),
      className: "w-40",
    },
    {
      key: "processed",
      header: "Обработан",
      render: (w) =>
        w.processed_at ? (
          new Date(w.processed_at).toLocaleString("ru")
        ) : (
          <span className="text-[var(--text-secondary)]">не обработан</span>
        ),
      className: "w-44",
    },
  ];
  return (
    <div className="space-y-3">
      <p className="text-sm text-[var(--text-secondary)]">
        Входящие события с невалидной подписью или те, до которых обработка не дошла. Подробнее — на
        странице{" "}
        <Link
          to="/webhooks"
          className="text-[var(--text-primary)] underline-offset-2 hover:underline"
        >
          /webhooks
        </Link>
        .
      </p>
      {error && <p className="text-sm text-[var(--danger)]">Не удалось загрузить список.</p>}
      <DataTable
        rows={rows}
        columns={columns}
        rowKey={(w) => w.id}
        empty={loading ? "Загрузка…" : "Сбоев нет — всё хорошо."}
      />
    </div>
  );
}

function SlaBadge({ minutes }: { minutes: number }) {
  const tone = minutes >= 120 ? "danger" : minutes >= 60 ? "warn" : "info";
  const cls =
    tone === "danger"
      ? "bg-[var(--danger-soft)] text-[var(--danger-fg)]"
      : tone === "warn"
        ? "bg-[var(--warning-soft)] text-[var(--warning-fg)]"
        : "bg-[var(--bg-muted)] text-[var(--text-secondary)]";
  return (
    <Badge tone={cls} dot={tone !== "info"}>
      {formatMinutes(minutes)}
    </Badge>
  );
}

function formatMinutes(minutes: number): string {
  if (minutes < 60) return `${minutes.toString()} мин`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours.toString()} ч`;
  const days = Math.floor(hours / 24);
  return `${days.toString()} дн`;
}
