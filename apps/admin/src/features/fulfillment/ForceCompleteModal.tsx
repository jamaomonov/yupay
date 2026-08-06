/** Modal for ``POST /admin/fulfillment/tasks/{id}/force-complete``.
 *
 * Opens from the FailedAutomaticTab when an admin wants to close a
 * low-balance task by hand: they topped up G2B off-platform (or
 * delivered the code from somewhere else) and now need to attach
 * the artifact + walk the order to ``delivered``.
 *
 * The form deliberately keeps the artifact wide-open — the operator
 * pastes a JSON blob whose shape matches what the customer should
 * see in ``/orders/{id}/deliveries``. We cap at three artifact_kinds
 * (matching the server-side check) plus a short proof URL for
 * internal audit. */

import { Button, Input } from "@yupay/ui";
import { X } from "lucide-react";
import { useEffect, useState } from "react";

import type { TaskAdminOut } from "./types";

import { useToast } from "@/components/Toast";
import { api, ApiError } from "@/lib/api";

type ArtifactKind = "voucher_code" | "topup_receipt" | "license_key";

interface Props {
  task: TaskAdminOut;
  onClose: () => void;
  onCompleted: () => void;
}

const DEFAULT_ARTIFACT: Record<ArtifactKind, string> = {
  voucher_code: '{\n  "code": "EXAMPLE-XXXX-YYYY"\n}',
  topup_receipt: '{\n  "manual_note": "выдано off-platform"\n}',
  license_key: '{\n  "license_key": "XXXX-XXXX-XXXX"\n}',
};

export function ForceCompleteModal({ task, onClose, onCompleted }: Props) {
  const toast = useToast();
  // Default the artifact_kind to whatever the supplier branch implies —
  // voucher → voucher_code, game → topup_receipt. Admin can still flip.
  const inferred: ArtifactKind = task.supplier === "g2b" ? "topup_receipt" : "voucher_code";
  const [kind, setKind] = useState<ArtifactKind>(inferred);
  const [artifactJson, setArtifactJson] = useState(DEFAULT_ARTIFACT[inferred]);
  const [adminNote, setAdminNote] = useState("");
  const [proofUrl, setProofUrl] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Close on Esc — operator reflex from every other modal.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const onKindChange = (next: ArtifactKind) => {
    setKind(next);
    // Reset the JSON skeleton when the kind changes so the placeholder
    // matches the new expected shape — but only if the admin hasn't
    // edited it yet (heuristic: still equals one of the defaults).
    if (Object.values(DEFAULT_ARTIFACT).includes(artifactJson)) {
      setArtifactJson(DEFAULT_ARTIFACT[next]);
    }
  };

  const submit = async () => {
    setError(null);
    if (!adminNote.trim()) {
      setError("Заполните примечание — это обязательная часть аудита.");
      return;
    }
    let artifact: unknown;
    try {
      artifact = JSON.parse(artifactJson);
    } catch (err) {
      setError(`Артефакт должен быть JSON: ${(err as Error).message}`);
      return;
    }
    if (typeof artifact !== "object" || artifact === null || Array.isArray(artifact)) {
      setError("Артефакт должен быть JSON-объектом, не массивом.");
      return;
    }
    setSubmitting(true);
    try {
      await api(`/api/v1/admin/fulfillment/tasks/${task.id}/force-complete`, {
        method: "POST",
        body: JSON.stringify({
          artifact_kind: kind,
          artifact,
          channel: "in_app",
          admin_note: adminNote.trim(),
          proof_url: proofUrl.trim() || null,
        }),
      });
      toast.success("Задача закрыта вручную, доставка записана");
      onCompleted();
    } catch (err) {
      if (err instanceof ApiError) {
        const body = err.body as { detail?: string; title?: string } | null;
        setError(body?.detail ?? body?.title ?? err.message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError("Неизвестная ошибка");
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="force-complete-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-md)]">
        <header className="flex items-center justify-between border-b border-[var(--border-subtle)] px-5 py-3">
          <h2 id="force-complete-title" className="text-base font-semibold">
            Завершить вручную · {task.id.slice(0, 8)}…
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)]"
            aria-label="Закрыть"
          >
            <X className="size-4" />
          </button>
        </header>

        <div className="space-y-4 overflow-y-auto px-5 py-4">
          <div className="rounded-md bg-[var(--bg-muted)] p-3 text-xs text-[var(--text-secondary)]">
            Принудительное завершение задачи поставщика. Используйте после того, как вручную
            пополнили баланс у поставщика и выдали клиенту код через другой канал. Действие пишется
            в audit, артефакт сохраняется в ``deliveries`` и становится виден клиенту.
          </div>

          <label className="block">
            <span className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
              Тип артефакта
            </span>
            <div className="mt-1 flex gap-3 text-sm">
              {(["voucher_code", "topup_receipt", "license_key"] as ArtifactKind[]).map((k) => (
                <label key={k} className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    value={k}
                    checked={kind === k}
                    onChange={() => {
                      onKindChange(k);
                    }}
                  />
                  <code className="text-xs">{k}</code>
                </label>
              ))}
            </div>
          </label>

          <label className="block">
            <span className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
              Артефакт (JSON)
            </span>
            <textarea
              value={artifactJson}
              onChange={(e) => {
                setArtifactJson(e.target.value);
              }}
              className="mt-1 min-h-32 w-full rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] px-3 py-2 font-mono text-xs"
              spellCheck={false}
            />
          </label>

          <label className="block">
            <span className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
              Примечание администратора (обязательно)
            </span>
            <Input
              value={adminNote}
              onChange={(e) => {
                setAdminNote(e.target.value);
              }}
              placeholder="Пополнили G2B напрямую, выдали через техподдержку"
            />
          </label>

          <label className="block">
            <span className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
              Proof URL (опционально, не показывается клиенту)
            </span>
            <Input
              value={proofUrl}
              onChange={(e) => {
                setProofUrl(e.target.value);
              }}
              placeholder="https://..."
            />
          </label>

          {error && (
            <p role="alert" className="text-sm text-[var(--danger)]">
              {error}
            </p>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-[var(--border-subtle)] px-5 py-3">
          <Button type="button" variant="ghost" onClick={onClose} disabled={submitting}>
            Отмена
          </Button>
          <Button
            type="button"
            onClick={() => {
              void submit();
            }}
            disabled={submitting}
          >
            {submitting ? "Сохранение…" : "Подтвердить"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
