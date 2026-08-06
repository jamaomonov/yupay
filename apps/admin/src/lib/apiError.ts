import { ApiError } from "./api";

/**
 * Human-readable message for anything thrown by the API client.
 *
 * The backend answers business-rule failures with an RFC 7807 envelope, so
 * `detail` (falling back to `title`) is the operator-facing sentence. FastAPI's
 * own request-validation failures use an *array*-shaped `detail`; those are
 * developer errors rather than something an operator can act on, so they fall
 * through to the generic message instead of rendering `[object Object]`.
 *
 * Extracted from the copies that had grown in `SkuEditPage` /
 * `BroadcastComposerPage` — one wording, one place to fix.
 */
export function extractApiMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const body = err.body as { detail?: unknown; title?: unknown } | null;
    const detail = body?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    const title = body?.title;
    if (typeof title === "string" && title.trim()) return title;
    return err.message;
  }
  if (err instanceof Error) return err.message;
  return "Что-то пошло не так";
}
