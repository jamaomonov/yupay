/**
 * BroadcastComposerPage — compose a new broadcast or edit an existing
 * draft/scheduled one: title, rich body (`TelegramEditor`), optional media,
 * locale targeting, and a Сейчас/Запланировать send mode, with a live phone
 * preview + audience count in the right column.
 *
 * Route reuse: both `/broadcasts/new` and `/broadcasts/:id/edit` render this
 * component — `params.id` selects create-vs-edit, same idiom as
 * `SkuEditPage`/`BrandEditPage` elsewhere in the admin.
 *
 * "Тест себе", "Сохранить черновик", and "Отправить"/"Запланировать" all
 * route through `ensureSaved()`, which upserts the draft (POST if brand new,
 * PATCH otherwise) before doing anything else. That's a superset of "save
 * the draft first if new": it also re-saves unsaved edits to an *existing*
 * draft before test/send/schedule, so the dispatched content always matches
 * what's on screen instead of whatever stale body the server had before.
 *
 * The three action buttons cover Тест себе / Сохранить черновик / Отправить
 * from the brief; "Запланировать" isn't a fourth button — it's what
 * "Отправить" becomes (label + endpoint) when the Сейчас/Запланировать radio
 * is set to "Запланировать".
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Input } from "@yupay/ui";
import { ArrowLeft } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { BroadcastPreview } from "./BroadcastPreview";

import type { AudienceCountOut, BroadcastOut, LocaleFilter, MediaType } from "./types";

import { Field } from "@/components/Field";
import { PageHeader } from "@/components/PageHeader";
import { Spinner } from "@/components/States";
import { TelegramEditor } from "@/components/TelegramEditor";
import { useToast } from "@/components/Toast";
import { BroadcastMediaUploader } from "@/features/broadcasts/BroadcastMediaUploader";
import { MAX_TEXT, MAX_WITH_MEDIA, visibleLength } from "@/features/broadcasts/telegramHtml";
import { ApiError, apiGet, apiPatch, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useDialog } from "@/lib/useDialog";

const LOCALE_CHIPS: { value: LocaleFilter | null; label: string }[] = [
  { value: null, label: "Все" },
  { value: "ru", label: "RU" },
  { value: "en", label: "EN" },
  { value: "uz", label: "UZ" },
];

/** ISO-8601 UTC instant -> the local-naive value an `<input type="datetime-local">` expects. */
function isoToLocalInput(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number): string => n.toString().padStart(2, "0");
  return (
    `${d.getFullYear().toString()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}`
  );
}

/** The reverse: a `datetime-local` value is local-naive — `new Date` parses it in the
 *  browser's local timezone, so `.toISOString()` is exactly the UTC instant the backend wants. */
function localInputToIsoUtc(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

/** Mirrors `SkuEditPage`'s `extractApiMessage` — same shape assumption
 *  (`detail` is a plain string), which holds for every *business-rule* 422
 *  this page can trigger (see the backend's RFC7807 envelope). The one case
 *  that wouldn't hold — FastAPI's own array-shaped `detail` for a
 *  bad-request-body validation failure — is pre-empted client-side by the
 *  `title.trim()` check in `ensureSaved`, so it should never actually reach
 *  this function in practice. */
function extractApiMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: string; title?: string } | null;
    return body?.detail ?? body?.title ?? err.message;
  }
  if (err instanceof Error) return err.message;
  return "Что-то пошло не так";
}

interface BroadcastWriteBody {
  title: string;
  body_html: string;
  media_type: MediaType;
  media_url: string | null;
  locale_filter: LocaleFilter | null;
  disable_web_page_preview: boolean;
}

/** A fresh key per write call — every broadcast write endpoint requires one (Task 6). */
function idemHeaders(): HeadersInit {
  return { "Idempotency-Key": crypto.randomUUID() };
}

export function BroadcastComposerPage() {
  const params = useParams<{ id?: string }>();
  const isNew = !params.id;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const [broadcastId, setBroadcastId] = useState<string | null>(params.id ?? null);
  const [title, setTitle] = useState("");
  const [bodyHtml, setBodyHtml] = useState("");
  const [mediaType, setMediaType] = useState<MediaType>("none");
  const [mediaUrl, setMediaUrl] = useState<string | null>(null);
  const [localeFilter, setLocaleFilter] = useState<LocaleFilter | null>(null);
  const [sendMode, setSendMode] = useState<"now" | "schedule">("now");
  const [scheduledLocal, setScheduledLocal] = useState("");
  const [confirmOpen, setConfirmOpen] = useState(false);

  // Guards the one-time hydration-from-server effect below so it never
  // clobbers in-progress edits on a background refetch.
  const hydratedRef = useRef(false);

  const detailQuery = useQuery<BroadcastOut>({
    queryKey: qk.broadcast(params.id ?? ""),
    queryFn: () => apiGet<BroadcastOut>(`/api/v1/admin/broadcasts/${params.id ?? ""}`),
    enabled: !isNew,
  });

  useEffect(() => {
    if (isNew || hydratedRef.current || !detailQuery.data) return;
    const b = detailQuery.data;
    setTitle(b.title);
    setBodyHtml(b.body_html);
    setMediaType(b.media_type);
    setMediaUrl(b.media_url);
    setLocaleFilter(b.locale_filter);
    setSendMode(b.scheduled_at ? "schedule" : "now");
    setScheduledLocal(b.scheduled_at ? isoToLocalInput(b.scheduled_at) : "");
    hydratedRef.current = true;
  }, [isNew, detailQuery.data]);

  const audienceQuery = useQuery<AudienceCountOut>({
    queryKey: qk.broadcastAudience(localeFilter),
    queryFn: () => {
      const search = new URLSearchParams();
      if (localeFilter) search.set("locale", localeFilter);
      const qs = search.toString();
      return apiGet<AudienceCountOut>(
        `/api/v1/admin/broadcasts/audience-count${qs ? `?${qs}` : ""}`,
      );
    },
  });

  const maxLength = mediaType === "none" ? MAX_TEXT : MAX_WITH_MEDIA;
  const charCount = visibleLength(bodyHtml);
  const overLimit = charCount > maxLength;
  // Mirrors the backend's `_validate_sendable`: "message is empty" means no
  // visible text AND no attached media, not just an empty body_html string.
  const hasContent = charCount > 0 || mediaType !== "none";
  const canDispatch = !overLimit && hasContent;
  const canSubmit = title.trim().length > 0;

  const saveDraft = useMutation<BroadcastOut, ApiError>({
    mutationFn: () => {
      const body: BroadcastWriteBody = {
        title: title.trim(),
        body_html: bodyHtml,
        media_type: mediaType,
        media_url: mediaUrl,
        locale_filter: localeFilter,
        disable_web_page_preview: true,
      };
      return broadcastId
        ? apiPatch<BroadcastOut>(`/api/v1/admin/broadcasts/${broadcastId}`, body, idemHeaders())
        : apiPost<BroadcastOut>("/api/v1/admin/broadcasts", body, idemHeaders());
    },
    onSuccess: (data) => {
      setBroadcastId(data.id);
      void qc.invalidateQueries({ queryKey: qk.broadcasts() });
      void qc.invalidateQueries({ queryKey: qk.broadcast(data.id) });
    },
  });

  const testMutation = useMutation<{ ok: boolean }, ApiError, string>({
    mutationFn: (id) =>
      apiPost<{ ok: boolean }>(`/api/v1/admin/broadcasts/${id}/test`, {}, idemHeaders()),
  });

  const sendMutation = useMutation<BroadcastOut, ApiError, string>({
    mutationFn: (id) =>
      apiPost<BroadcastOut>(`/api/v1/admin/broadcasts/${id}/send`, {}, idemHeaders()),
  });

  const scheduleMutation = useMutation<BroadcastOut, ApiError, { id: string; scheduledAt: string }>(
    {
      mutationFn: ({ id, scheduledAt }) =>
        apiPost<BroadcastOut>(
          `/api/v1/admin/broadcasts/${id}/schedule`,
          { scheduled_at: scheduledAt },
          idemHeaders(),
        ),
    },
  );

  const busy =
    saveDraft.isPending ||
    testMutation.isPending ||
    sendMutation.isPending ||
    scheduleMutation.isPending;

  /** Upsert the draft with whatever is currently in form state, returning its id. */
  async function ensureSaved(): Promise<string> {
    if (!canSubmit) {
      throw new Error("Введите заголовок");
    }
    const saved = await saveDraft.mutateAsync();
    return saved.id;
  }

  async function handleSaveDraftClick(): Promise<void> {
    try {
      await ensureSaved();
      toast.success("Черновик сохранён");
      void navigate("/broadcasts");
    } catch (err) {
      toast.error(extractApiMessage(err));
    }
  }

  async function handleTestClick(): Promise<void> {
    try {
      const id = await ensureSaved();
      const result = await testMutation.mutateAsync(id);
      if (result.ok) {
        toast.success("Тест отправлен вам в Telegram");
      } else {
        toast.error("Не удалось отправить тест — попробуйте позже");
      }
    } catch (err) {
      toast.error(extractApiMessage(err));
    }
  }

  function handleDispatchClick(): void {
    if (sendMode === "schedule" && !localInputToIsoUtc(scheduledLocal)) {
      toast.error("Укажите дату и время отправки");
      return;
    }
    setConfirmOpen(true);
  }

  async function handleConfirm(): Promise<void> {
    try {
      const id = await ensureSaved();
      if (sendMode === "now") {
        await sendMutation.mutateAsync(id);
        toast.success("Рассылка отправляется");
      } else {
        const iso = localInputToIsoUtc(scheduledLocal);
        if (!iso) {
          toast.error("Некорректная дата");
          return;
        }
        await scheduleMutation.mutateAsync({ id, scheduledAt: iso });
        toast.success("Рассылка запланирована");
      }
      setConfirmOpen(false);
      void qc.invalidateQueries({ queryKey: qk.broadcasts() });
      void navigate("/broadcasts");
    } catch (err) {
      toast.error(extractApiMessage(err));
    }
  }

  if (!isNew && detailQuery.isLoading) {
    return <Spinner label="Загрузка…" />;
  }
  if (!isNew && detailQuery.isError) {
    return (
      <div className="space-y-3">
        <p className="text-sm text-[var(--danger)]">Не удалось загрузить рассылку.</p>
        <Button variant="ghost" onClick={() => navigate("/broadcasts")}>
          <ArrowLeft className="size-4" />К списку
        </Button>
      </div>
    );
  }

  const dispatchLabel = sendMode === "schedule" ? "Запланировать" : "Отправить";

  return (
    <div className="space-y-4">
      <PageHeader
        title={isNew ? "Новая рассылка" : title || "Рассылка"}
        description="Сообщение в Telegram по сегменту пользователей."
        actions={
          <>
            <Button type="button" variant="ghost" onClick={() => navigate("/broadcasts")}>
              Отмена
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void handleTestClick()}
              disabled={busy || !canSubmit || !canDispatch}
            >
              Тест себе
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => void handleSaveDraftClick()}
              disabled={busy || !canSubmit}
            >
              Сохранить черновик
            </Button>
            <Button
              type="button"
              onClick={handleDispatchClick}
              disabled={busy || !canSubmit || !canDispatch}
            >
              {dispatchLabel}
            </Button>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <section className="space-y-4 rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)] lg:col-span-2">
          <Field label="Заголовок" hint="Только для админки — получатели его не видят." required>
            {({ inputProps }) => (
              <Input
                {...inputProps}
                value={title}
                onChange={(e) => {
                  setTitle(e.target.value);
                }}
                placeholder="Например: «Летняя акция»"
                maxLength={500}
              />
            )}
          </Field>

          <div>
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
              Текст сообщения
            </span>
            <TelegramEditor value={bodyHtml} onChange={setBodyHtml} maxLength={maxLength} />
          </div>

          <div>
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
              Медиа
            </span>
            <BroadcastMediaUploader
              value={mediaUrl}
              mediaType={mediaType}
              onChange={(url, type) => {
                if (!url) {
                  setMediaUrl(null);
                  setMediaType("none");
                } else {
                  setMediaUrl(url);
                  setMediaType(type);
                }
              }}
              disabled={busy}
            />
          </div>

          <div>
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
              Аудитория
            </span>
            <div className="flex flex-wrap gap-1.5">
              {LOCALE_CHIPS.map((chip) => (
                <button
                  key={chip.label}
                  type="button"
                  onClick={() => {
                    setLocaleFilter(chip.value);
                  }}
                  aria-pressed={localeFilter === chip.value}
                  className={[
                    "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                    localeFilter === chip.value
                      ? "border-[var(--accent)] bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]"
                      : "border-[var(--border-default)] bg-[var(--bg-surface)] text-[var(--text-secondary)] hover:bg-[var(--bg-muted)]",
                  ].join(" ")}
                >
                  {chip.label}
                </button>
              ))}
            </div>
          </div>

          <div>
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-[var(--text-secondary)]">
              Когда отправить
            </span>
            <div className="flex flex-wrap items-center gap-4">
              <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                <input
                  type="radio"
                  name="send-mode"
                  checked={sendMode === "now"}
                  onChange={() => {
                    setSendMode("now");
                  }}
                />
                Сейчас
              </label>
              <label className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                <input
                  type="radio"
                  name="send-mode"
                  checked={sendMode === "schedule"}
                  onChange={() => {
                    setSendMode("schedule");
                  }}
                />
                Запланировать
              </label>
              {sendMode === "schedule" && (
                <input
                  type="datetime-local"
                  value={scheduledLocal}
                  onChange={(e) => {
                    setScheduledLocal(e.target.value);
                  }}
                  aria-label="Дата и время отправки"
                  className="h-9 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-2 text-sm text-[var(--text-primary)]"
                />
              )}
            </div>
          </div>

          {!canDispatch && (
            <p className="text-xs text-[var(--danger-fg)]">
              {overLimit
                ? `Текст длиннее лимита (${charCount.toString()} / ${maxLength.toString()}).`
                : "Добавьте текст или медиа перед отправкой."}
            </p>
          )}
        </section>

        <aside className="space-y-4">
          <p className="text-sm font-medium text-[var(--text-primary)]">
            {title || "Без названия"}
          </p>
          <BroadcastPreview bodyHtml={bodyHtml} mediaType={mediaType} mediaUrl={mediaUrl} />

          <section className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
            <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
              Аудитория
            </h3>
            {audienceQuery.isLoading ? (
              <Spinner label="Считаем…" size="sm" />
            ) : (
              <p className="text-2xl font-semibold text-[var(--text-primary)]">
                {audienceQuery.data?.count ?? "—"}
              </p>
            )}
            <p className="text-xs text-[var(--text-secondary)]">
              {localeFilter ? `Локаль: ${localeFilter.toUpperCase()}` : "Все локали"}
            </p>
          </section>
        </aside>
      </div>

      {confirmOpen && (
        <ConfirmDispatchDialog
          mode={sendMode}
          audienceCount={audienceQuery.data?.count ?? null}
          scheduledLocal={scheduledLocal}
          busy={sendMutation.isPending || scheduleMutation.isPending || saveDraft.isPending}
          onCancel={() => {
            setConfirmOpen(false);
          }}
          onConfirm={() => void handleConfirm()}
        />
      )}
    </div>
  );
}

interface ConfirmDispatchDialogProps {
  mode: "now" | "schedule";
  audienceCount: number | null;
  scheduledLocal: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}

/** Dependency-free confirm modal — same fixed-overlay + small-panel idiom as
 *  `SaveSegmentButton`'s inline dialog (no dialog primitives in `@yupay/ui` yet). */
function ConfirmDispatchDialog({
  mode,
  audienceCount,
  scheduledLocal,
  busy,
  onCancel,
  onConfirm,
}: ConfirmDispatchDialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();
  useDialog({ open: true, onClose: onCancel, containerRef: dialogRef });

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 px-4 pt-[12vh] backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div className="w-full max-w-md rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 text-[var(--text-primary)] shadow-[var(--shadow-md)]">
        <h2 id={titleId} className="mb-3 text-sm font-semibold">
          {mode === "schedule" ? "Запланировать рассылку?" : "Отправить рассылку сейчас?"}
        </h2>
        <p className="text-sm text-[var(--text-secondary)]">
          Получат сообщение:{" "}
          <strong className="text-[var(--text-primary)]">{audienceCount ?? "…"}</strong>{" "}
          пользователей.
        </p>
        {mode === "schedule" && (
          <p className="mt-2 text-sm text-[var(--text-secondary)]">
            Время отправки: <strong className="text-[var(--text-primary)]">{scheduledLocal}</strong>
          </p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
            Отмена
          </Button>
          <Button type="button" onClick={onConfirm} disabled={busy}>
            {busy ? "Отправка…" : "Подтвердить"}
          </Button>
        </div>
      </div>
    </div>
  );
}
