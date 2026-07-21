/**
 * BroadcastPreview — read-only "phone bubble" mock of how the message will
 * render inside Telegram.
 *
 * Purely presentational: no queries, no state. Renders `previewHtml(bodyHtml)`
 * via `dangerouslySetInnerHTML` — safe because `previewHtml` is whitelist-
 * guarded (see `telegramHtml.ts`'s docstring) and never emits a tag it didn't
 * explicitly construct itself — plus a small thumbnail/chip for whichever
 * `MediaType` is attached. Uses the admin's own semantic tokens (not a fixed
 * Telegram-brand green) so the bubble stays correct in both Dim Slate themes.
 */

import { FileText, Film } from "lucide-react";

import type { MediaType } from "./types";

import { previewHtml } from "@/features/broadcasts/telegramHtml";

interface Props {
  bodyHtml: string;
  mediaType: MediaType;
  mediaUrl: string | null;
}

function MediaThumb({ mediaType, mediaUrl }: { mediaType: MediaType; mediaUrl: string | null }) {
  if (mediaType === "none" || !mediaUrl) return null;

  if (mediaType === "photo" || mediaType === "animation") {
    return <img src={mediaUrl} alt="" className="mb-2 max-h-56 w-full rounded-lg object-cover" />;
  }

  const Icon = mediaType === "video" ? Film : FileText;
  const label = mediaType === "video" ? "Видео" : "Документ";
  return (
    <div className="mb-2 flex items-center gap-2 rounded-lg bg-[var(--bg-surface)] p-2 text-xs text-[var(--text-secondary)]">
      <Icon className="size-5 shrink-0" aria-hidden />
      <span className="truncate">{label}</span>
    </div>
  );
}

export function BroadcastPreview({ bodyHtml, mediaType, mediaUrl }: Props) {
  const html = previewHtml(bodyHtml);
  const hasMedia = mediaType !== "none" && Boolean(mediaUrl);
  const isEmpty = html.trim().length === 0 && !hasMedia;

  return (
    <section className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-sm)]">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--text-secondary)]">
        Как увидит получатель
      </h3>
      <div className="mx-auto max-w-sm overflow-hidden rounded-2xl border border-[var(--border-default)] bg-[var(--bg-muted)]">
        <div className="flex items-center gap-2 border-b border-[var(--border-subtle)] px-3 py-2">
          <div className="grid size-7 shrink-0 place-items-center rounded-full bg-[var(--accent)] text-xs font-semibold text-[var(--text-on-accent)]">
            Y
          </div>
          <span className="text-sm font-medium text-[var(--text-primary)]">YuPay</span>
        </div>
        <div className="p-3">
          <div className="inline-block max-w-full rounded-xl bg-[var(--bg-accent-soft)] p-3">
            <MediaThumb mediaType={mediaType} mediaUrl={mediaUrl} />
            {isEmpty ? (
              <p className="text-sm italic text-[var(--text-secondary)]">
                Пусто — начните вводить текст
              </p>
            ) : (
              <div
                className="whitespace-pre-wrap break-words text-sm text-[var(--text-primary)]"
                dangerouslySetInnerHTML={{ __html: html }}
              />
            )}
          </div>
        </div>
      </div>
    </section>
  );
}
