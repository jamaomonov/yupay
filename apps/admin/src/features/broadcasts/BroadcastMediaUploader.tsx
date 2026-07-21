/**
 * BroadcastMediaUploader — drag&drop / click-to-pick media picker for the
 * broadcast composer. Same presign→PUT handshake as ``ImageUploader`` (see
 * that component's header for the two-step-upload rationale, ADR-0018):
 *
 *   1. POST /admin/media/presign-upload  →  { upload_url, public_url, … }
 *   2. PUT  upload_url  (Content-Type pinned by step 1)
 *
 * It is scoped to ``kind: "broadcast_media"`` (storage skeleton, Task 3),
 * which is why it isn't just a re-parameterized ``ImageUploader``: the
 * accept list is wider (photo / GIF / video / PDF, not just static images),
 * the cap is 20 MB instead of 5 MB, and — unlike ImageUploader — the parent
 * needs to know *which* Telegram media kind was uploaded
 * (``BroadcastOut.media_type``), so ``onChange`` reports both the new
 * public URL and the ``MediaType`` derived from the file's MIME type.
 */

import { useCallback, useId, useState } from "react";

import type { MediaType } from "./types";

import { apiPost } from "@/lib/api";

interface PresignOut {
  upload_url: string;
  public_url: string;
  key: string;
  content_type: string;
  expires_in: number;
  max_bytes: number;
}

interface Props {
  /** Current stored URL — whatever lives in the broadcast's ``media_url`` column. */
  value: string | null | undefined;
  /**
   * Known media type of ``value`` (typically ``BroadcastOut.media_type`` when
   * editing an existing broadcast). Only used to label the chip before a
   * fresh upload's own derived type is known — a plain re-render of an
   * already-uploaded value doesn't need it.
   */
  mediaType?: MediaType | null;
  /**
   * Fired with the new public URL and its derived ``MediaType`` after a
   * successful upload, or with ``("", "none")`` when the admin clears the
   * current media.
   */
  onChange: (url: string, mediaType: MediaType) => void;
  /** Optional hint label rendered under the dropzone. */
  hint?: string;
  /** Disable while a parent form is submitting. */
  disabled?: boolean;
}

const ACCEPT_LIST = [
  "image/png",
  "image/jpeg",
  "image/webp",
  "image/gif",
  "video/mp4",
  "application/pdf",
];
const MAX_BYTES = 20 * 1024 * 1024;

const MEDIA_TYPE_LABELS: Record<MediaType, string> = {
  none: "Без медиа",
  photo: "Фото",
  video: "Видео",
  animation: "GIF",
  document: "Документ",
};

/** Telegram media kind implied by an uploaded file's MIME type. */
function deriveMediaType(mimeType: string): MediaType {
  switch (mimeType) {
    case "image/gif":
      return "animation";
    case "video/mp4":
      return "video";
    case "application/pdf":
      return "document";
    default:
      return "photo";
  }
}

function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024).toString()} KB`;
  return `${bytes.toString()} B`;
}

/**
 * Best-effort filename recovered from a public URL's last path segment.
 * Used only as a fallback when the component is remounted against an
 * already-uploaded ``value`` (e.g. reopening a draft broadcast) and the
 * original ``File`` — and its real name — is no longer in memory.
 */
function deriveNameFromUrl(url: string): string {
  try {
    const { pathname } = new URL(url);
    const last = pathname.split("/").pop();
    return last !== undefined && last.length > 0 ? decodeURIComponent(last) : url;
  } catch {
    return url;
  }
}

interface FileMeta {
  name: string;
  size: number;
  type: MediaType;
}

export function BroadcastMediaUploader({ value, mediaType, onChange, hint, disabled }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  // Set right after a successful upload so the chip can show the real
  // filename/size for *this* session; falls back to the URL + the
  // ``mediaType`` prop when the component mounts against an existing value.
  const [fileMeta, setFileMeta] = useState<FileMeta | null>(null);
  // Native ``<label htmlFor={id}>`` opens the file picker for us — see
  // ImageUploader's note on why we avoid a manual ``input.click()``.
  const inputId = useId();
  // Boolean-normalized once: ``disabled`` is an optional prop (may be
  // ``undefined``), so a plain ``disabled || busy`` trips
  // ``@typescript-eslint/prefer-nullish-coalescing`` even though ``??``
  // would be wrong here — we want busy to win over an explicit
  // ``disabled={false}``, which nullish coalescing wouldn't check.
  const isDisabled = Boolean(disabled) || busy;

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      if (!ACCEPT_LIST.includes(file.type)) {
        setError("Только PNG / JPEG / WebP / GIF / MP4 / PDF.");
        return;
      }
      if (file.size > MAX_BYTES) {
        setError(`Файл больше ${(MAX_BYTES / 1024 / 1024).toString()} MB.`);
        return;
      }
      setBusy(true);
      try {
        const presign = await apiPost<PresignOut>("/api/v1/admin/media/presign-upload", {
          kind: "broadcast_media",
          content_type: file.type,
          size_bytes: file.size,
        });
        const putRes = await fetch(presign.upload_url, {
          method: "PUT",
          headers: { "Content-Type": file.type },
          body: file,
        });
        if (!putRes.ok) {
          throw new Error(`R2 upload failed: ${putRes.status.toString()} ${putRes.statusText}`);
        }
        const derived = deriveMediaType(file.type);
        setFileMeta({ name: file.name, size: file.size, type: derived });
        onChange(presign.public_url, derived);
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "Ошибка загрузки");
      } finally {
        setBusy(false);
      }
    },
    [onChange],
  );

  const onInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) void handleFile(file);
      // Reset so picking the *same* file twice still fires change.
      e.target.value = "";
    },
    [handleFile],
  );

  const onDrop = (event: React.DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragOver(false);
    if (isDisabled) return;
    const file = event.dataTransfer.files[0];
    if (file) {
      void handleFile(file);
    }
  };

  const clear = useCallback(() => {
    setFileMeta(null);
    onChange("", "none");
  }, [onChange]);

  if (value) {
    const name = fileMeta?.name ?? deriveNameFromUrl(value);
    const typeLabel = MEDIA_TYPE_LABELS[fileMeta?.type ?? mediaType ?? "photo"];
    const sizeLabel = fileMeta ? formatSize(fileMeta.size) : null;

    return (
      <div className="space-y-2">
        <div className="flex items-center gap-3 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] p-2">
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm text-[var(--text-primary)]">{name}</p>
            <p className="text-xs text-[var(--text-secondary)]">
              {typeLabel}
              {sizeLabel ? ` · ${sizeLabel}` : ""}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <label
              htmlFor={inputId}
              className={[
                "cursor-pointer text-xs text-[var(--accent)] underline",
                isDisabled ? "pointer-events-none opacity-60" : "",
              ].join(" ")}
            >
              Заменить
            </label>
            <button
              type="button"
              className="text-xs text-[var(--danger-fg)] underline"
              onClick={clear}
              disabled={isDisabled}
            >
              Убрать
            </button>
          </div>
        </div>
        <input
          id={inputId}
          type="file"
          accept={ACCEPT_LIST.join(",")}
          className="hidden"
          onChange={onInputChange}
        />
        {busy && <p className="text-xs text-[var(--text-secondary)]">Загрузка...</p>}
        {error && <p className="text-xs text-[var(--danger-fg)]">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          if (!isDisabled) setDragOver(true);
        }}
        onDragLeave={() => {
          setDragOver(false);
        }}
        onDrop={onDrop}
        className={[
          "flex cursor-pointer flex-col items-center justify-center rounded-md border-2 border-dashed p-4 text-sm transition-colors",
          dragOver
            ? "border-[var(--accent)] bg-[var(--accent-soft)]"
            : "border-[var(--border-default)] bg-[var(--bg-surface)]",
          isDisabled ? "pointer-events-none opacity-60" : "",
        ].join(" ")}
      >
        <input
          id={inputId}
          type="file"
          accept={ACCEPT_LIST.join(",")}
          className="hidden"
          onChange={onInputChange}
        />
        <p className="text-[var(--text-secondary)]">
          {busy ? "Загрузка..." : "Перетащи или нажми, чтобы загрузить"}
        </p>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          {hint ?? `Фото / GIF / видео / PDF, до ${(MAX_BYTES / 1024 / 1024).toString()} MB`}
        </p>
      </label>
      {error && <p className="text-xs text-[var(--danger-fg)]">{error}</p>}
    </div>
  );
}
