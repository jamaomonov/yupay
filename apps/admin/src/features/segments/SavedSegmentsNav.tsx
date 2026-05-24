/**
 * Sidebar block — "Мои сегменты".
 *
 * Tiny block under the main NAV that lists the calling admin's saved
 * segments. Click navigates straight to the saved path+params; hover reveals
 * a delete button so cleanup doesn't need a separate management screen.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bookmark, Trash2 } from "lucide-react";
import { NavLink } from "react-router-dom";

import { buildSegmentHref, type SavedSegment, type SavedSegmentList } from "./types";

import { type ApiError, apiDelete, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

export function SavedSegmentsNav() {
  const qc = useQueryClient();
  const q = useQuery<SavedSegmentList>({
    queryKey: qk.savedSegments(),
    queryFn: () => apiGet<SavedSegmentList>("/api/v1/admin/segments"),
    staleTime: 30_000,
  });

  const remove = useMutation<void, ApiError, string>({
    mutationFn: (id) => apiDelete(`/api/v1/admin/segments/${id}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.savedSegments() });
    },
  });

  const items = q.data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <section
      className="border-t border-[var(--border-default)] px-3 pb-2 pt-3"
      aria-label="Мои сегменты"
    >
      <p className="mb-1 px-3 text-[10px] font-medium uppercase tracking-wide text-[var(--text-secondary)]">
        Мои сегменты
      </p>
      <ul className="space-y-0.5">
        {items.map((s) => (
          // ``group-focus-within`` reveals the delete button when the segment link
          // or the button itself receives focus — without it, the button stayed
          // off-DOM for keyboard / touch users (a11y-audit #2, WCAG 2.1.1 + 2.5.7).
          <li key={s.id} className="group relative">
            <SegmentLink segment={s} />
            <button
              type="button"
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                if (window.confirm(`Удалить сегмент «${s.name}»?`)) {
                  remove.mutate(s.id);
                }
              }}
              aria-label={`Удалить сегмент ${s.name}`}
              className={[
                "absolute right-2 top-1/2 grid size-7 -translate-y-1/2 place-items-center rounded",
                "text-[var(--text-secondary)] hover:bg-[var(--bg-surface)] hover:text-[var(--danger)]",
                "opacity-0 transition-opacity",
                "group-focus-within:opacity-100 group-hover:opacity-100",
                "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-sidebar)]",
              ].join(" ")}
            >
              <Trash2 className="size-3.5" />
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SegmentLink({ segment }: { segment: SavedSegment }) {
  const href = buildSegmentHref(segment);
  return (
    <NavLink
      to={href}
      className={({ isActive }) =>
        [
          "flex items-center gap-2 rounded-md px-3 py-1.5 pr-8 text-xs transition-colors",
          isActive
            ? "bg-[var(--bg-muted)] text-[var(--text-primary)]"
            : "hover:bg-[var(--bg-muted)]/60 text-[var(--text-secondary)] hover:text-[var(--text-primary)]",
        ].join(" ")
      }
      title={`${segment.path} (${Object.keys(segment.params).length.toString()} параметров)`}
    >
      <Bookmark className="size-3.5 shrink-0" />
      <span className="truncate">{segment.name}</span>
    </NavLink>
  );
}
