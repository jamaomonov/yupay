/**
 * ImageUploader — drag&drop / click-to-pick image picker that uploads
 * directly to Cloudflare R2 via a presigned PUT URL and reports the
 * resulting public URL back to the parent form.
 *
 * Why not stream through the API: see ADR-0018. Two-step handshake:
 *
 *   1. POST /admin/media/presign-upload  →  { upload_url, public_url, … }
 *   2. PUT  upload_url  (multipart-free; Content-Type pinned by step 1)
 *
 * The component is a controlled input: ``value`` is the current
 * stored URL (whatever lives in the DB column), ``onChange`` is fired
 * with the new public_url after a successful PUT — exactly what
 * react-hook-form's ``Controller`` needs.
 */

import { useCallback, useId, useState } from "react";

import { apiPost } from "@/lib/api";

export type MediaKind = "brand_logo" | "brand_hero" | "product_image" | "sku_image";

interface PresignOut {
  upload_url: string;
  public_url: string;
  key: string;
  content_type: string;
  expires_in: number;
  max_bytes: number;
}

interface Props {
  value: string | null | undefined;
  onChange: (url: string) => void;
  kind: MediaKind;
  /** Optional hint label rendered under the dropzone. */
  hint?: string;
  /** Disable while a parent form is submitting. */
  disabled?: boolean;
}

// Raster only — SVG is scriptable and served from the public CDN origin (stored
// XSS); the API rejects it, so don't offer it in the picker either.
const ACCEPT_LIST = ["image/png", "image/jpeg", "image/webp"];
const MAX_BYTES = 5 * 1024 * 1024;

export function ImageUploader({ value, onChange, kind, hint, disabled }: Props) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  // Native ``<label htmlFor={id}>`` opens the file picker for us, so we
  // don't need a ref + manual ``input.click()`` — that pattern was
  // double-firing the dialog on some browsers because the manual
  // ``click()`` and the bubbled label click overlapped.
  const inputId = useId();

  const handleFile = useCallback(
    async (file: File) => {
      setError(null);
      if (!ACCEPT_LIST.includes(file.type)) {
        setError("Только PNG / JPEG / WebP / SVG.");
        return;
      }
      if (file.size > MAX_BYTES) {
        setError(`Файл больше ${(MAX_BYTES / 1024 / 1024).toString()} MB.`);
        return;
      }
      setBusy(true);
      try {
        const presign = await apiPost<PresignOut>("/api/v1/admin/media/presign-upload", {
          kind,
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
        onChange(presign.public_url);
      } catch (exc) {
        setError(exc instanceof Error ? exc.message : "Ошибка загрузки");
      } finally {
        setBusy(false);
      }
    },
    [kind, onChange],
  );

  const onDrop = (event: React.DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragOver(false);
    if (disabled || busy) return;
    const file = event.dataTransfer.files[0];
    if (file) {
      void handleFile(file);
    }
  };

  return (
    <div className="space-y-2">
      {value && (
        <div className="flex items-center gap-3 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] p-2">
          <img
            src={value}
            alt=""
            className="h-16 w-16 rounded object-contain"
            // Catalog images often live on third-party hosts (legacy URLs);
            // failing to load shouldn't break the form layout.
            onError={(e) => {
              e.currentTarget.style.visibility = "hidden";
            }}
          />
          <div className="min-w-0 flex-1">
            <p className="truncate text-xs text-[var(--text-secondary)]">{value}</p>
            <button
              type="button"
              className="mt-1 text-xs text-[var(--danger-fg)] underline"
              onClick={() => {
                onChange("");
              }}
              disabled={disabled || busy}
            >
              Удалить ссылку
            </button>
          </div>
        </div>
      )}
      <label
        htmlFor={inputId}
        onDragOver={(e) => {
          e.preventDefault();
          if (!disabled && !busy) setDragOver(true);
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
          disabled || busy ? "pointer-events-none opacity-60" : "",
        ].join(" ")}
      >
        <input
          id={inputId}
          type="file"
          accept={ACCEPT_LIST.join(",")}
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void handleFile(file);
            // Reset so picking the *same* file twice still fires change.
            e.target.value = "";
          }}
        />
        <p className="text-[var(--text-secondary)]">
          {busy ? "Загрузка..." : "Перетащи или нажми, чтобы загрузить"}
        </p>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">
          {hint ?? `PNG / JPEG / WebP / SVG, до ${(MAX_BYTES / 1024 / 1024).toString()} MB`}
        </p>
      </label>
      {error && <p className="text-xs text-[var(--danger-fg)]">{error}</p>}
    </div>
  );
}
