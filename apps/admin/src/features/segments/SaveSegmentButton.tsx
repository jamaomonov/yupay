/**
 * Save-current-filter button.
 *
 * Reads the current pathname + search-params via React Router and POSTs them
 * to /admin/segments. Used on filter-rich pages (Orders, Payments, Fulfillment,
 * Triage) — drop the component next to the filter row and forget about it.
 *
 * The modal is dependency-free (no shadcn / dialog primitives in the kit yet),
 * just a fixed overlay with a small form.
 */

import { useId, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";
import { Bookmark, X } from "lucide-react";

import { Button, Input } from "@yupay/ui";

import { Field } from "@/components/Field";
import { type ApiError, apiPost } from "@/lib/api";
import { qk } from "@/lib/queryKeys";
import { useDialog } from "@/lib/useDialog";

import type { SavedSegment, SavedSegmentIn } from "./types";

export function SaveSegmentButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => { setOpen(true); }}
        className="inline-flex items-center gap-1.5 rounded-md border border-[var(--border-default)] px-3 py-1.5 text-sm text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text-primary)]"
      >
        <Bookmark className="size-4" />
        Сохранить фильтр
      </button>
      {open && <SaveSegmentDialog onClose={() => { setOpen(false); }} />}
    </>
  );
}

function SaveSegmentDialog({ onClose }: { onClose: () => void }) {
  const location = useLocation();
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const titleId = useId();
  useDialog({
    open: true,
    onClose,
    containerRef: dialogRef,
    initialFocus: () => inputRef.current?.focus(),
  });

  const params: Record<string, string> = {};
  for (const [k, v] of new URLSearchParams(location.search).entries()) {
    params[k] = v;
  }

  const create = useMutation<SavedSegment, ApiError, SavedSegmentIn>({
    mutationFn: (body) => apiPost<SavedSegment>("/api/v1/admin/segments", body),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.savedSegments() });
      onClose();
    },
    onError: (err) => {
      if (err.status === 409) {
        setLocalError("Сегмент с таким именем уже есть.");
      } else {
        setLocalError(describeError(err));
      }
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setLocalError("Введите имя");
      return;
    }
    setLocalError(null);
    create.mutate({
      name: trimmed,
      path: location.pathname,
      params,
    });
  };

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 px-4 pt-[12vh] backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-md rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 text-[var(--text-primary)] shadow-[var(--shadow-md)]"
      >
        <header className="mb-3 flex items-center justify-between">
          <h2 id={titleId} className="text-sm font-semibold">
            Сохранить сегмент
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] hover:text-[var(--text-primary)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-surface)]"
            aria-label="Закрыть"
          >
            <X className="size-4" aria-hidden />
          </button>
        </header>

        <Field
          label="Имя сегмента"
          hint="не длиннее 80 символов"
          error={localError ?? undefined}
          required
        >
          {({ inputProps }) => (
            <Input
              {...inputProps}
              ref={inputRef}
              value={name}
              onChange={(e) => { setName(e.target.value); }}
              placeholder="Например: «висящие Click старше 60 мин»"
              maxLength={80}
            />
          )}
        </Field>

        <p className="mt-3 text-xs text-[var(--text-secondary)]">
          Сохраняем текущий URL:{" "}
          <code className="text-[var(--text-primary)]">
            {location.pathname}
            {location.search || ""}
          </code>
        </p>

        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button type="submit" disabled={create.isPending}>
            {create.isPending ? "Сохранение…" : "Сохранить"}
          </Button>
        </div>
      </form>
    </div>
  );
}

function describeError(err: ApiError): string {
  const body = err.body as { detail?: string } | null;
  return body?.detail ?? err.message;
}
