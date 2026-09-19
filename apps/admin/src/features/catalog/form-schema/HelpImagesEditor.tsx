/** Visual editor for a single `FormField.help_images` — the ordered
 * "Где найти?" screenshot walkthrough the storefront shows next to a
 * player-id field. Each image is a thumbnail with an optional per-locale
 * caption; operators upload, reorder, and remove them here.
 *
 * Uploads reuse the same direct-to-R2 handshake as `ImageUploader` /
 * `BlogEditorToolbar` (ADR-0018): presign, PUT straight to R2, keep the
 * returned public URL. Nothing here talks to the product endpoint — the
 * URL only becomes part of the product once the page's own Save button is
 * pressed, same as every other field on this page. The file itself already
 * exists in R2 the moment the PUT succeeds; an unsaved product just never
 * references it.
 */

import { Input } from "@yupay/ui";
import { ArrowDown, ArrowUp, ImagePlus, Loader2, Trash2 } from "lucide-react";
import { useId, useState } from "react";
import { type Control, type UseFormRegister, useFieldArray } from "react-hook-form";

import type { HelpImage } from "../types";

import { uploadRasterMedia } from "@/lib/uploadMedia";

const LOCALES = ["ru", "en", "uz"] as const;

/** Mirrors the API's cap on `FormField.help_images`. */
export const MAX_HELP_IMAGES = 6;

interface Props {
  // The parent form's full schema lives in ProductEditPage.tsx; RequiredFieldsEditor
  // already threads `Control<any>` / `UseFormRegister<any>` down through FieldRow for
  // the same reason — following that convention here rather than inventing a second one.
  control: Control<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  register: UseFormRegister<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  /** Path to this field's `help_images` array, e.g. `required_fields.0.help_images`. */
  name: string;
}

interface UploadTask {
  id: string;
  fileName: string;
  status: "uploading" | "error";
  message: string | null;
}

export function HelpImagesEditor({ control, register, name }: Props) {
  const { fields, append, remove, move } = useFieldArray({ control, name });
  // `fields` comes back structurally untyped because `control` is `Control<any>` —
  // narrow each row to the known HelpImage shape it's built from (see the comment
  // on Props above for why the parent passes `any` down in the first place).
  const rows = fields as (HelpImage & { id: string })[];
  const [tasks, setTasks] = useState<UploadTask[]>([]);
  const inputId = useId();

  const atCap = rows.length >= MAX_HELP_IMAGES;

  function pickFiles(fileList: FileList): void {
    const slots = MAX_HELP_IMAGES - rows.length;
    const files = Array.from(fileList).slice(0, Math.max(slots, 0));
    void (async () => {
      for (const file of files) {
        const taskId = `${Date.now().toString()}-${Math.random().toString(36).slice(2)}`;
        setTasks((prev) => [
          ...prev,
          { id: taskId, fileName: file.name, status: "uploading", message: null },
        ]);
        try {
          const url = await uploadRasterMedia("field_help_image", file);
          append({ url, caption: { ru: "", en: "", uz: "" } } satisfies HelpImage);
          setTasks((prev) => prev.filter((t) => t.id !== taskId));
        } catch (exc) {
          const message = exc instanceof Error ? exc.message : "Ошибка загрузки";
          setTasks((prev) =>
            prev.map((t) => (t.id === taskId ? { ...t, status: "error", message } : t)),
          );
        }
      }
    })();
  }

  return (
    <div>
      <div className="text-xs font-medium uppercase text-[var(--text-secondary)]">
        Скриншоты — «Где найти?»
      </div>
      <p className="mt-1 text-[11px] text-[var(--text-secondary)]">
        Порядок — это порядок шагов инструкции: покупатель листает их по очереди. До{" "}
        {MAX_HELP_IMAGES} изображений на поле. Подпись необязательна.
      </p>

      {rows.length > 0 && (
        <ul className="mt-2 space-y-2">
          {rows.map((row, idx) => (
            <li
              key={row.id}
              className="flex gap-3 rounded-md border border-[var(--border-default)] bg-[var(--bg-surface)] p-2"
            >
              <img
                src={row.url}
                alt=""
                className="h-16 w-16 shrink-0 rounded object-cover"
                onError={(e) => {
                  e.currentTarget.style.visibility = "hidden";
                }}
              />
              <div className="grid min-w-0 flex-1 grid-cols-1 gap-2 sm:grid-cols-3">
                {LOCALES.map((l) => (
                  <Input
                    key={l}
                    {...register(`${name}.${idx.toString()}.caption.${l}`)}
                    placeholder={`Подпись, ${l.toUpperCase()}`}
                  />
                ))}
              </div>
              <div className="flex shrink-0 flex-col gap-1">
                <button
                  type="button"
                  disabled={idx === 0}
                  onClick={() => {
                    move(idx, idx - 1);
                  }}
                  aria-label={`Переместить изображение ${(idx + 1).toString()} выше`}
                  className="grid size-7 place-items-center rounded text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] disabled:pointer-events-none disabled:opacity-40"
                >
                  <ArrowUp className="size-3.5" />
                </button>
                <button
                  type="button"
                  disabled={idx === rows.length - 1}
                  onClick={() => {
                    move(idx, idx + 1);
                  }}
                  aria-label={`Переместить изображение ${(idx + 1).toString()} ниже`}
                  className="grid size-7 place-items-center rounded text-[var(--text-secondary)] hover:bg-[var(--bg-muted)] disabled:pointer-events-none disabled:opacity-40"
                >
                  <ArrowDown className="size-3.5" />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    remove(idx);
                  }}
                  aria-label={`Удалить изображение ${(idx + 1).toString()}`}
                  className="grid size-7 place-items-center rounded text-[var(--danger-fg)] hover:bg-[var(--bg-muted)]"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {tasks.length > 0 && (
        <ul className="mt-2 space-y-1">
          {tasks.map((t) => (
            <li
              key={t.id}
              className={
                t.status === "uploading"
                  ? "flex items-center gap-2 text-xs text-[var(--text-secondary)]"
                  : "flex items-center gap-2 text-xs text-[var(--danger-fg)]"
              }
            >
              {t.status === "uploading" ? (
                <>
                  <Loader2 className="size-3.5 animate-spin" />
                  Загрузка «{t.fileName}»…
                </>
              ) : (
                <>
                  «{t.fileName}»: {t.message}
                  <button
                    type="button"
                    onClick={() => {
                      setTasks((prev) => prev.filter((x) => x.id !== t.id));
                    }}
                    className="underline"
                  >
                    Скрыть
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}

      {atCap ? (
        <p className="mt-2 text-xs text-[var(--text-secondary)]">
          Достигнут максимум {MAX_HELP_IMAGES} изображений на поле — удали одно, чтобы добавить
          новое.
        </p>
      ) : (
        <label
          htmlFor={inputId}
          className="mt-2 flex w-fit cursor-pointer items-center gap-2 rounded-md border border-dashed border-[var(--border-default)] px-3 py-2 text-xs text-[var(--text-secondary)] hover:border-[var(--border-strong)]"
        >
          <input
            id={inputId}
            type="file"
            multiple
            accept="image/png,image/jpeg,image/webp"
            className="hidden"
            onChange={(e) => {
              const { files } = e.target;
              e.target.value = "";
              if (files && files.length > 0) pickFiles(files);
            }}
          />
          <ImagePlus className="size-4" />
          Добавить изображение
        </label>
      )}
    </div>
  );
}
