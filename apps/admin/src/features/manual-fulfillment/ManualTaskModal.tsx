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

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input, Select } from "@yupay/ui";
import { X } from "lucide-react";
import { useId, useMemo, useRef, useState } from "react";

import {
  ARTIFACT_KIND_LABEL,
  type ArtifactKind,
  type DeliveryChannel,
  type ManualCompleteIn,
  type ManualFailIn,
} from "./types";

import type { TaskAdminOut } from "@/features/fulfillment/types";
import { orderActorOf, orderActorText, type OrderAdminOut } from "@/features/orders/types";

import { Field } from "@/components/Field";
import { useToast } from "@/components/Toast";
import { type ApiError, apiGet, apiPost } from "@/lib/api";
import { extractApiMessage } from "@/lib/apiError";
import { qk } from "@/lib/queryKeys";
import { useDialog } from "@/lib/useDialog";

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
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("complete");
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  const tabListIdComplete = useId();
  const tabListIdFail = useId();
  const completeTabId = useId();
  const failTabId = useId();
  useDialog({ open: true, onClose, containerRef: dialogRef });

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
      apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/tasks/${task.id}/complete`, body),
    onSuccess: () => {
      // Goods just went to a customer — closing the modal in silence left the
      // operator unsure whether it landed.
      toast.success("Заказ выдан, доставка записана");
      void qc.invalidateQueries({ queryKey: qk.manualQueue() });
      void qc.invalidateQueries({ queryKey: qk.fulfillmentTasks({}) });
      void qc.invalidateQueries({ queryKey: qk.order(task.order_id) });
      onClose();
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  const fail = useMutation<TaskAdminOut, ApiError, ManualFailIn>({
    mutationFn: (body) =>
      apiPost<TaskAdminOut>(`/api/v1/admin/fulfillment/tasks/${task.id}/fail`, body),
    onSuccess: () => {
      toast.success("Задача отклонена");
      void qc.invalidateQueries({ queryKey: qk.manualQueue() });
      void qc.invalidateQueries({ queryKey: qk.fulfillmentTasks({}) });
      void qc.invalidateQueries({ queryKey: qk.order(task.order_id) });
      onClose();
    },
    onError: (err) => {
      toast.error(extractApiMessage(err));
    },
  });

  const onTabKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      setTab((t) => (t === "complete" ? "fail" : "complete"));
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      setTab((t) => (t === "fail" ? "complete" : "fail"));
    }
  };
  const panelId = tab === "complete" ? tabListIdComplete : tabListIdFail;

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm md:items-center"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="relative w-full max-w-2xl rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-primary)] shadow-[var(--shadow-md)] ring-1 ring-black/5">
        <header className="flex items-center justify-between gap-3 border-b border-[var(--border-default)] px-4 py-3">
          <div className="min-w-0">
            <p className="text-xs uppercase text-[var(--text-secondary)]">Задача</p>
            <p id={titleId} className="truncate font-mono text-sm">
              {task.id}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-surface)]"
            aria-label="Закрыть"
          >
            <X className="size-4" aria-hidden />
          </button>
        </header>

        <ContextBlock task={task} order={orderQuery.data ?? null} item={item} />

        <div className="border-b border-[var(--border-default)] px-4">
          <div role="tablist" aria-label="Действия с задачей" className="flex gap-1">
            <TabButton
              active={tab === "complete"}
              id={completeTabId}
              controls={tabListIdComplete}
              onClick={() => {
                setTab("complete");
              }}
              onKeyDown={onTabKeyDown}
            >
              Завершить
            </TabButton>
            <TabButton
              active={tab === "fail"}
              id={failTabId}
              controls={tabListIdFail}
              onClick={() => {
                setTab("fail");
              }}
              onKeyDown={onTabKeyDown}
            >
              Отклонить
            </TabButton>
          </div>
        </div>

        <div
          id={panelId}
          role="tabpanel"
          aria-labelledby={tab === "complete" ? completeTabId : failTabId}
          className="p-4"
        >
          {tab === "complete" ? (
            <CompleteForm
              onSubmit={(body) => {
                complete.mutate(body);
              }}
              pending={complete.isPending}
              error={complete.error}
            />
          ) : (
            <FailForm
              onSubmit={(body) => {
                fail.mutate(body);
              }}
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
  id,
  controls,
  onClick,
  onKeyDown,
  children,
}: {
  active: boolean;
  id: string;
  controls: string;
  onClick: () => void;
  onKeyDown?: (e: React.KeyboardEvent) => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      id={id}
      aria-selected={active}
      aria-controls={controls}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
      onKeyDown={onKeyDown}
      className={[
        "border-b-2 px-3 py-2 text-sm font-medium transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-surface)]",
        active
          ? "border-[var(--accent)] text-[var(--text-primary)]"
          : "border-transparent text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
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
    : (item?.sku_id ?? "—");
  // Same three-arm derivation the orders screens use — a merchant order has
  // no `guest_email` and no `user_id`, and used to read «—» here.
  const customer = order ? orderActorText(orderActorOf(order)) : "…";
  const fulfillmentData = item?.fulfillment_data ?? {};
  const dataEntries = Object.entries(fulfillmentData).filter(([, v]) => v !== null && v !== "");

  return (
    <section className="space-y-3 border-b px-4 py-3 text-sm">
      <div className="grid grid-cols-2 gap-3">
        <KeyValue label="Заказ" value={task.order_id} mono />
        <KeyValue
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
        <KeyValue label="Товар" value={headline} />
        <KeyValue label="Клиент" value={customer} />
        <KeyValue
          label="Сумма"
          value={
            order
              ? `${Number.parseFloat(order.total_charged).toLocaleString("ru", {
                  maximumFractionDigits: 2,
                })} ${order.currency}`
              : "—"
          }
        />
        <KeyValue label="Кол-во" value={item ? String(item.qty) : "—"} />
      </div>

      <div>
        <p className="text-xs font-medium uppercase text-[var(--text-secondary)]">
          Данные для выдачи
        </p>
        {dataEntries.length === 0 ? (
          <p className="mt-1 text-[var(--text-secondary)]">— нет дополнительных полей —</p>
        ) : (
          <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-1">
            {dataEntries.map(([k, v]) => (
              <div key={k} className="flex justify-between gap-3">
                <dt className="text-[var(--text-secondary)]">{k}</dt>
                <dd className="truncate font-mono">{String(v)}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </section>
  );
}

function KeyValue({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-xs font-medium uppercase text-[var(--text-secondary)]">{label}</p>
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
  // Internal-only proof link for receipts — screenshot, PDF, ticket URL.
  // Stays on the task; never copied into the customer-facing delivery.
  const [proofUrl, setProofUrl] = useState("");

  // Escape hatch: raw JSON editor for non-standard artifact shapes.
  const [rawMode, setRawMode] = useState(false);
  const [rawJson, setRawJson] = useState("");
  const [rawError, setRawError] = useState<string | null>(null);

  const buildArtifact = (): Record<string, unknown> | null => {
    if (rawMode) {
      try {
        const parsed: unknown = JSON.parse(rawJson);
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
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
      proof_url: proofUrl.trim() || null,
    });
  };

  return (
    <form className="space-y-4" onSubmit={handleSubmit}>
      <div className="grid grid-cols-2 gap-3">
        <FormField label="Тип артефакта">
          <Select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value as ArtifactKind);
            }}
            containerClassName="w-full"
          >
            {Object.entries(ARTIFACT_KIND_LABEL).map(([v, label]) => (
              <option key={v} value={v}>
                {label}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label="Канал доставки">
          <Select
            value={channel}
            onChange={(e) => {
              setChannel(e.target.value as DeliveryChannel);
            }}
            containerClassName="w-full"
          >
            {CHANNELS.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      {!rawMode ? (
        <div className="space-y-3">
          {kind === "voucher_code" && (
            <FormField label="Код">
              <Input
                value={code}
                onChange={(e) => {
                  setCode(e.target.value);
                }}
                placeholder="MANUAL-XXXX-YYYY"
                autoFocus
              />
            </FormField>
          )}
          {kind === "license_key" && (
            <FormField label="Ключ">
              <Input
                value={key}
                onChange={(e) => {
                  setKey(e.target.value);
                }}
                placeholder="AAAA-BBBB-CCCC-DDDD"
                autoFocus
              />
            </FormField>
          )}
          {kind === "topup_receipt" && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="ID операции">
                  <Input
                    value={externalId}
                    onChange={(e) => {
                      setExternalId(e.target.value);
                    }}
                    placeholder="op_123456"
                    autoFocus
                  />
                </FormField>
                <FormField label="Заметка (необязательно)">
                  <Input
                    value={receiptNote}
                    onChange={(e) => {
                      setReceiptNote(e.target.value);
                    }}
                    placeholder="Зачислено 1 000 UC"
                  />
                </FormField>
              </div>
              <FormField label="URL пруфа (внутреннее, клиент не видит)">
                <Input
                  type="url"
                  value={proofUrl}
                  onChange={(e) => {
                    setProofUrl(e.target.value);
                  }}
                  placeholder="https://drive.example.com/screenshot.png"
                />
              </FormField>
            </>
          )}
        </div>
      ) : (
        <FormField label="JSON артефакта">
          <textarea
            value={rawJson}
            onChange={(e) => {
              setRawJson(e.target.value);
            }}
            className="min-h-32 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 font-mono text-xs"
            placeholder='{"code": "ABC-123"}'
          />
        </FormField>
      )}

      <label className="flex items-center gap-2 text-sm text-[var(--text-secondary)]">
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
          onChange={(e) => {
            setAdminNote(e.target.value);
          }}
          className="min-h-20 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-sm"
        />
      </FormField>

      {rawError && <p className="text-sm text-[var(--danger)]">{rawError}</p>}
      {error && <p className="text-sm text-[var(--danger)]">{describeError(error)}</p>}

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
      <Field label="Причина (видна в журнале заказа)" error={localError ?? undefined} required>
        {({ inputProps }) => (
          <Input
            {...inputProps}
            value={reason}
            onChange={(e) => {
              setReason(e.target.value);
            }}
            placeholder="нет в наличии / аккаунт заблокирован / …"
            autoFocus
          />
        )}
      </Field>

      <Field label="Внутренняя заметка (не видна клиенту)">
        {({ inputProps }) => (
          <textarea
            {...inputProps}
            value={adminNote}
            onChange={(e) => {
              setAdminNote(e.target.value);
            }}
            className="focus-visible:ring-[var(--accent)]/30 min-h-20 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 text-sm text-[var(--text-primary)] focus-visible:border-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-surface)]"
          />
        )}
      </Field>

      <p className="rounded-md border border-[var(--border-default)] bg-[var(--bg-muted)] p-3 text-xs text-[var(--text-secondary)]">
        Заказ останется в статусе «в работе». Возврат денег инициируется отдельно в разделе
        «Платежи» → «Refund», чтобы выдача и возврат оставались под раздельным контролем.
      </p>

      {error && (
        <p className="text-sm text-[var(--danger-fg)]" role="alert">
          {describeError(error)}
        </p>
      )}

      <div className="flex justify-end gap-2">
        <Button type="submit" variant="danger" disabled={pending}>
          {pending ? "Сохранение…" : "Отклонить"}
        </Button>
      </div>
    </form>
  );
}

// CompleteForm still uses the legacy FormField wrapper because it has 6+ inputs
// that switch shape per ``artifact_kind`` — porting those onto <Field> needs a
// design pass, not a mechanical rewrite. Style tokens updated to Dim Slate so
// it matches the rest of the modal.
function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
        {label}
      </span>
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
