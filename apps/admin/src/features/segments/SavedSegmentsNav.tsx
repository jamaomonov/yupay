/**
 * Sidebar block — "Мои сегменты".
 *
 * Tiny block under the main NAV that lists the calling admin's saved
 * segments. Click navigates straight to the saved path+params; hover reveals
 * a delete button so cleanup doesn't need a separate management screen.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink } from "react-router-dom";
import { Bookmark, Trash2 } from "lucide-react";

import { type ApiError, apiDelete, apiGet } from "@/lib/api";
import { qk } from "@/lib/queryKeys";

import { buildSegmentHref, type SavedSegment, type SavedSegmentList } from "./types";

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
      className="border-t border-[--color-border] px-3 pb-2 pt-3"
      aria-label="Мои сегменты"
    >
      <p className="mb-1 px-3 text-[10px] font-medium uppercase tracking-wide text-[--color-muted]">
        Мои сегменты
      </p>
      <ul className="space-y-0.5">
        {items.map((s) => (
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
              className="absolute right-2 top-1/2 hidden -translate-y-1/2 rounded p-1 text-[--color-muted] hover:bg-[--color-bg] hover:text-[--color-danger] group-hover:block"
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
            ? "bg-[--color-subtle] text-[--color-fg]"
            : "text-[--color-muted] hover:bg-[--color-subtle]/60 hover:text-[--color-fg]",
        ].join(" ")
      }
      title={`${segment.path} (${Object.keys(segment.params).length.toString()} параметров)`}
    >
      <Bookmark className="size-3.5 shrink-0" />
      <span className="truncate">{segment.name}</span>
    </NavLink>
  );
}
