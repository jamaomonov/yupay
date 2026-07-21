/**
 * Hand-typed mirrors of the broadcasts OpenAPI DTOs
 * (`apps/api/src/yupay/modules/broadcasts`, regenerated into
 * `docs/api/openapi.json` by Task 6). Field names/nullability match the
 * schema exactly — see `BroadcastOut`, `BroadcastListOut`, `RecipientOut`,
 * `RecipientListOut`, and `AudienceCountOut` in that file.
 */

/** `BroadcastOut.media_type` / presign `kind: "broadcast_media"` payload shape. */
export type MediaType = "none" | "photo" | "video" | "animation" | "document";

/** `BroadcastOut.status` — the broadcast's FSM state. */
export type BroadcastStatus = "draft" | "scheduled" | "sending" | "sent" | "failed" | "canceled";

/** `BroadcastOut.locale_filter` — `null` means "all locales". */
export type LocaleFilter = "ru" | "en" | "uz";

/** `RecipientOut.status` — per-recipient delivery outcome. */
export type RecipientStatus = "pending" | "sent" | "failed" | "blocked";

/** Full admin view of a broadcast row: content + FSM state + delivery counters. */
export interface BroadcastOut {
  id: string;
  title: string;
  status: BroadcastStatus;
  body_html: string;
  media_type: MediaType;
  media_url: string | null;
  media_file_id: string | null;
  locale_filter: LocaleFilter | null;
  disable_web_page_preview: boolean;
  scheduled_at: string | null;
  total_recipients: number;
  sent_count: number;
  failed_count: number;
  blocked_count: number;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
}

/** A page of {@link BroadcastOut} plus the total matching count. */
export interface BroadcastListOut {
  items: BroadcastOut[];
  total: number;
}

/**
 * One targeted recipient row.
 *
 * `tg_chat_id` is a Postgres `bigint`, serialized as a `string` (money-rule
 * for big ids) so it survives round-tripping through a JS `number` without
 * precision loss.
 */
export interface RecipientOut {
  user_id: string;
  tg_chat_id: string;
  status: RecipientStatus;
  error: string | null;
  sent_at: string | null;
}

/** A page of {@link RecipientOut} plus the total matching count. */
export interface RecipientListOut {
  items: RecipientOut[];
  total: number;
}

/** Response of the audience-size preview endpoint. */
export interface AudienceCountOut {
  count: number;
}

/** `BroadcastOut.status` → human label (ru), mirrors `promo`'s `StatusBadge` idiom.
 *  Shared between `BroadcastsListPage` and `BroadcastDetailPage` so the six-state
 *  vocabulary never drifts between the list and detail views. */
export const STATUS_LABEL: Record<BroadcastStatus, string> = {
  draft: "Черновик",
  scheduled: "Запланирована",
  sending: "Отправляется",
  sent: "Отправлено",
  failed: "Ошибка",
  canceled: "Отменена",
};

/** `BroadcastOut.status` → pill tone. Same semantic tokens as the orders list
 *  (`STATUS_TONE` in `features/orders/types.ts`) so colour meaning stays
 *  consistent across the admin: muted = at rest, warning = upcoming,
 *  accent = in progress, success = done, danger = failed. */
export const STATUS_TONE: Record<BroadcastStatus, string> = {
  draft: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
  scheduled: "bg-[var(--warning-soft)] text-[var(--warning-fg)]",
  sending: "bg-[var(--bg-accent-soft)] text-[var(--accent-soft-fg)]",
  sent: "bg-[var(--success-soft)] text-[var(--success-fg)]",
  failed: "bg-[var(--danger-soft)] text-[var(--danger-fg)]",
  canceled: "bg-[var(--bg-muted)] text-[var(--text-secondary)]",
};
