/**
 * Manual task modal — opened from ManualQueuePage when the admin picks a
 * row in the queue.
 *
 * Two tabs share the read-only context block (fulfillment_data, brand,
 * product, customer, qty, price):
 *
 *   • "Завершить" — artifact_kind picker drives one of three preset forms;
 *     a checkbox flips to raw JSON when an admin needs a non-standard shape.
 *     POST /admin/fulfillment/tasks/{id}/complete.
 *   • "Отклонить" — required reason + optional internal note. POST /fail.
 *
 * On success the modal closes and the queue + order + task caches all
 * invalidate so the queue page reflects reality on the next paint.
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";

import { Button, Input } from "@yupay/ui";

import { ApiError, apiGet, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import type { TaskAdminOut } from "@/features/fulfillment/types";
import type { OrderAdminOut } from "@/features/orders/types";

import {
  ARTIFACT_KIND_LABEL,
  type ArtifactKind,
  type DeliveryChannel,
  type ManualCompleteIn,
  type ManualFailIn,
} from "./types";

interface Props {
  task: TaskAdminOut;
  onClose: () => void;
}

type Tab = "complete" | "fail";

const CHANNELS: { value: DeliveryChannel; label: string }[] = [
  { value: "in_app", label: "В приложении" },
  { value: "email", label: "Email" },
  { value: "telegram", label: "Telegram" },
];

export function ManualTaskModal({ task, onClose }: Props) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>("complete");

  // Pull the full order to surface brand/product/customer + the item's
  // fulfillment_data. The queue already pre-fetched this with the same
  // queryKey, so this is usually a cache hit.
  const orderQuery = useQuery<OrderAdminOut>({
    queryKey: qk.order(task.order_id),
    queryFn: () => apiGet<OrderAdminOut>(`/api/v1/admin/orders/${task.order_id}`),
  });
  const item = useMemo(
    () => orderQuery.data?.items.find((i) => i.id === task.order_item_id) ?? null,
    [orderQuery.data, task.order_item_id],
  );

  const complete = useMutation<TaskAdminOut, ApiError, ManualCompleteIn>({
    mutationFn: (body) =>
      apiPost<TaskAdminOut>(
        `/api/v1/admin/fulfillment/tasks/${task.id}/complete`,
        body,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.manualQueue() });
      void qc.invalidateQueries({ queryKey: qk.fulfillmentTasks({}) });
      void qc.invalidateQueries({ queryKey: qk.order(task.order_id) });
      onClose();
    },
  });

  const fail = useMutation<TaskAdminOut, ApiError, ManualFailIn>({
    mutationFn: (body) =>
      apiPost<TaskAdminOut>(
        `/api/v1/admin/fulfillment/tasks/${task.id}/fail`,
        body,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.manualQueue() });
      void qc.invalidateQueries({ queryKey: qk.fulfillmentTasks({}) });
      void qc.invalidateQueries({ queryKey: qk.order(task.order_id) });
      onClose();
    },
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm md:items-center"
      role="dialog"
      aria-modal="true"
    >
      {/* ``text-[--color-fg]`` is explicit so the modal renders the same
          contrast whether the parent tree happens to be in a darker
          surface (sidebar etc.). The outer backdrop also gets a blur so
          a light-mode admin can't mistake the modal for "transparent". */}
      <div className="relative w-full max-w-2xl rounded-lg border border-[--color-border] bg-[--color-bg] text-[--color-fg] shadow-2xl ring-1 ring-black/5">
        <header className="flex items-center justify-between gap-3 border-b px-4 py-3">
          <div className="min-w-0">
            <p className="text-xs uppercase text-[--color-muted]">Задача</p>
            <p className="truncate font-mono text-sm">{task.id}</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-[--color-muted] hover:bg-[--color-subtle]"
            aria-label="Закрыть"
          >
            <X className="size-4" />
          </button>
        </header>

        <ContextBlock task={task} order={orderQuery.data ?? null} item={item} />

        <div className="border-b px-4">
          <div className="flex gap-1">
            <TabButton active={tab === "complete"} onClick={() => setTab("complete")}>
              Завершить
            </TabButton>
            <TabButton active={tab === "fail"} onClick={() => setTab("fail")}>
              Отклонить
            </TabButton>
          </div>
        </div>

        <div className="p-4">
          {tab === "complete" ? (
            <CompleteForm
              onSubmit={(body) => complete.mutate(body)}
              pending={complete.isPending}
              error={complete.error}
            />
          ) : (
            <FailForm
              onSubmit={(body) => fail.mutate(body)}
              pending={fail.isPending}
              error={fail.error}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "border-b-2 px-3 py-2 text-sm font-medium transition-colors",
        active
          ? "border-[--color-brand] text-[--color-fg]"
          : "border-transparent text-[--color-muted] hover:text-[--color-fg]",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function ContextBlock({
  task,
  order,
  item,
}: {
  task: TaskAdminOut;
  order: OrderAdminOut | null;
  item: OrderAdminOut["items"][number] | null;
}) {
  const display = item?.display ?? null;
  const headline = display
    ? display.brand_name
      ? `${display.brand_name} · ${display.denomination ?? display.sku_code}`
      : `${display.product_name || display.product_slug} · ${display.denomination ?? display.sku_code}`
    : item?.sku_id ?? "—";
  const customer = order
    ? order.guest_email ?? (order.user_id ? `user:${order.user_id}` : "—")
    : "…";
  const fulfillmentData = item?.fulfillment_data ?? {};
  const dataEntries = Object.entries(fulfillmentData).filter(
    ([, v]) => v !== null && v !== "",
  );

  return (
    <section className="space-y-3 border-b px-4 py-3 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <Field label="Заказ" value={task.order_id} mono />
        <Field
          label="Создан"
          value={
            order
              ? new Date(order.created_at).toLocaleString("ru", {
                  day: "2-digit",
                  month: "short",
                  hour: "2-digit",
                  minute: "2-digit",
                })
              : "…"
          }
        />
        <Field label="Товар" value={headline} />
        <Field label="Клиент" value={customer} />
        <Field
          label="Сумма"
          value={
            order
              ? `${Number.parseFloat(order.total_charged).toLocaleString("ru", {
                  maximumFractionDigits: 2,
                })} ${order.currency}`
              : "—"
          }
        />
        <Field label="Кол-во" value={item ? String(item.qty) : "—"} />
      </div>

      <div>
        <p className="text-xs font-medium uppercase text-[--color-muted]">
          Данные для выдачи
        </p>
        {dataEntries.length === 0 ? (
          <p className="mt-1 text-[--color-muted]">— нет дополнительных полей —</p>
        ) : (
          <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1">
            {dataEntries.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3">
                <dt className="text-[--color-muted]">{k}</dt>
                <dd className="truncate font-mono">{String(v)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </section>
  );
}

function Field({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-xs font-medium uppercase text-[--color-muted]">{label}</p>
      <p className={["truncate", mono ? "font-mono" : ""].join(" ")}>{value}</p>
    </div>
  );
}

// ---------- Complete form ----------

function CompleteForm({
  onSubmit,
  pending,
  error,
}: {
  onSubmit: (body: ManualCompleteIn) => void;
  pending: boolean;
  error: ApiError | null;
}) {
  const [kind, setKind] = useState<ArtifactKind>("voucher_code");
  const [channel, setChannel] = useState<DeliveryChannel>("in_app");
  const [adminNote, setAdminNote] = useState("");

  // Template fields per artifact_kind.
  const [code, setCode] = useState("");
  const [key, setKey] = useState("");
  const [externalId, setExternalId] = useState("");
  const [receiptNote, setReceiptNote] = useState("");

  // Escape hatch: raw JSON editor for non-standard artifact shapes.
  const [rawMode, setRawMode] = useState(false);
  const [rawJson, setRawJson] = useState("");
  const [rawError, setRawError] = useState<string | null>(null);

  const buildArtifact = (): Record<string, unknown> | null => {
    if (rawMode) {
      try {
        const parsed: unknown = JSON.parse(rawJson);
        if (
          !parsed ||
          typeof parsed !== "object" ||
          Array.isArray(parsed)
        ) {
          setRawError("Артефакт должен быть JSON-объектом");
          return null;
        }
        return parsed as Record<string, unknown>;
      } catch {
        setRawError("Некорректный JSON");
        return null;
      }
    }
    if (kind === "voucher_code") {
      if (!code.trim()) return null;
      return { code: code.trim() };
    }
    if (kind === "license_key") {
      if (!key.trim()) return null;
      return { key: key.trim() };
    }
    // topup_receipt
    if (!externalId.trim()) return null;
    const artifact: Record<string, unknown> = { external_id: externalId.trim() };
    if (receiptNote.trim()) artifact.note = receiptNote.trim();
    return artifact;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setRawError(null);
    const artifact = buildArtifact();
    if (!artifact) {
      if (!rawMode) setRawError("Заполните поле артефакта");
      return;
    }
    onSubmit({
      artifact_kind: kind,
      artifact,
      channel,
      admin_note: adminNote.trim() || null,
    });
  };

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <div className="grid grid-cols-2 gap-3">
        <FormField label="Тип артефакта">
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value as ArtifactKind)}
            className="flex h-10 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 text-sm"
          >
            {Object.entries(ARTIFACT_KIND_LABEL).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </select>
        </FormField>
        <FormField label="Канал доставки">
          <select
            value={channel}
            onChange={(e) => setChannel(e.target.value as DeliveryChannel)}
            className="flex h-10 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 text-sm"
          >
            {CHANNELS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </FormField>
      </div>

      {!rawMode ? (
        <div className="space-y-3">
          {kind === "voucher_code" && (
            <FormField label="Код">
              <Input
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="MANUAL-XXXX-YYYY"
                autoFocus
              />
            </FormField>
          )}
          {kind === "license_key" && (
            <FormField label="Ключ">
              <Input
                value={key}
                onChange={(e) => setKey(e.target.value)}
                placeholder="AAAA-BBBB-CCCC-DDDD"
                autoFocus
              />
            </FormField>
          )}
          {kind === "topup_receipt" && (
            <div className="grid grid-cols-2 gap-3">
              <FormField label="ID операции">
                <Input
                  value={externalId}
                  onChange={(e) => setExternalId(e.target.value)}
                  placeholder="op_123456"
                  autoFocus
                />
              </FormField>
              <FormField label="Заметка (необязательно)">
                <Input
                  value={receiptNote}
                  onChange={(e) => setReceiptNote(e.target.value)}
                  placeholder="Зачислено 1 000 UC"
                />
              </FormField>
            </div>
          )}
        </div>
      ) : (
        <FormField label="JSON артефакта">
          <textarea
            value={rawJson}
            onChange={(e) => setRawJson(e.target.value)}
            className="min-h-32 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 py-2 font-mono text-xs"
            placeholder='{"code": "ABC-123"}'
          />
        </FormField>
      )}

      <label className="flex items-center gap-2 text-sm text-[--color-muted]">
        <input
          type="checkbox"
          checked={rawMode}
          onChange={(e) => {
            setRawMode(e.target.checked);
            setRawError(null);
          }}
        />
        Расширенный режим (JSON)
      </label>

      <FormField label="Внутренняя заметка (не видна клиенту)">
        <textarea
          value={adminNote}
          onChange={(e) => setAdminNote(e.target.value)}
          className="min-h-20 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 py-2 text-sm"
        />
      </FormField>

      {rawError && (
        <p className="text-sm text-[--color-danger]">{rawError}</p>
      )}
      {error && (
        <p className="text-sm text-[--color-danger]">{describeError(error)}</p>
      )}

      <div className="flex justify-end gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? "Сохранение…" : "Завершить выдачу"}
        </Button>
      </div>
    </form>
  );
}

// ---------- Fail form ----------

function FailForm({
  onSubmit,
  pending,
  error,
}: {
  onSubmit: (body: ManualFailIn) => void;
  pending: boolean;
  error: ApiError | null;
}) {
  const [reason, setReason] = useState("");
  const [adminNote, setAdminNote] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = reason.trim();
    if (!trimmed) {
      setLocalError("Укажите причину");
      return;
    }
    setLocalError(null);
    onSubmit({ reason: trimmed, admin_note: adminNote.trim() || null });
  };

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <FormField label="Причина (видна в журнале заказа)">
        <Input
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder="нет в наличии / аккаунт заблокирован / …"
          autoFocus
        />
      </FormField>

      <FormField label="Внутренняя заметка (не видна клиенту)">
        <textarea
          value={adminNote}
          onChange={(e) => setAdminNote(e.target.value)}
          className="min-h-20 w-full rounded-md border border-[--color-border] bg-[--color-bg] px-3 py-2 text-sm"
        />
      </FormField>

      <p className="rounded-md border border-[--color-border] bg-[--color-subtle]/40 p-3 text-xs text-[--color-muted]">
        Заказ останется в статусе «в работе». Возврат денег инициируется
        отдельно в разделе «Платежи» → «Refund», чтобы выдача и возврат
        оставались под раздельным контролем.
      </p>

      {localError && (
        <p className="text-sm text-[--color-danger]">{localError}</p>
      )}
      {error && (
        <p className="text-sm text-[--color-danger]">{describeError(error)}</p>
      )}

      <div className="flex justify-end gap-2">
        <Button type="submit" variant="danger" disabled={pending}>
          {pending ? "Сохранение…" : "Отклонить"}
        </Button>
      </div>
    </form>
  );
}

function FormField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-xs font-medium uppercase text-[--color-muted]">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function describeError(error: ApiError): string {
  const body = error.body as { detail?: string } | null | string;
  if (body && typeof body === "object" && typeof body.detail === "string") {
    return body.detail;
  }
  return error.message;
}
