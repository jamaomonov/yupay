import { ChevronDown, ChevronUp, Inbox } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import { EmptyState, TableSkeleton } from "./States";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
  /** When set, the column header becomes clickable. The accessor returns the
   *  raw value used for sorting. Numbers / strings / nulls are handled
   *  natively; everything else gets ``String(...)``-ified. */
  sortAccessor?: (row: T) => string | number | Date | null | undefined;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  empty?: string;
  /** Optional caption read by screen-readers — surfaces what this table is for. */
  ariaLabel?: string;
  /** Sync state for `aria-busy` while parent's query refetches. */
  busy?: boolean;
  /** Show a `<TableSkeleton>` instead of the empty state on the very first
   *  load — keeps the layout from jumping when the data arrives. */
  loading?: boolean;
  onRowClick?: (row: T) => void;
  /** Highlight the row whose ``rowKey`` matches — used when a click
   *  expands a detail panel elsewhere and we want the source row to stay
   *  visually anchored. */
  selectedKey?: string | null;
  /** Skip the client-side sort entirely (e.g. table already comes pre-sorted
   *  and the dataset is server-paginated). Headers stay non-clickable. */
  sortable?: boolean;
}

type SortDir = "asc" | "desc";

export function DataTable<T>({
  rows,
  columns,
  rowKey,
  empty,
  ariaLabel,
  busy = false,
  loading = false,
  onRowClick,
  selectedKey = null,
  sortable = true,
}: Props<T>) {
  const [sort, setSort] = useState<{ key: string; dir: SortDir } | null>(null);

  const sorted = useMemo(() => {
    if (!sort || !sortable) return rows;
    const col = columns.find((c) => c.key === sort.key && c.sortAccessor);
    if (!col?.sortAccessor) return rows;
    const acc = col.sortAccessor;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const va = normalise(acc(a));
      const vb = normalise(acc(b));
      if (va === null && vb === null) return 0;
      if (va === null) return 1; // nulls sink to the bottom regardless of dir
      if (vb === null) return -1;
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }, [rows, columns, sort, sortable]);

  if (rows.length === 0) {
    // First load: render a TableSkeleton to preserve the shape; otherwise the
    // explicit EmptyState reads better both visually and for screen readers.
    if (loading) {
      return <TableSkeleton rows={6} columns={columns.length} />;
    }
    return <EmptyState icon={Inbox} title={empty ?? "Пока пусто."} tone="muted" />;
  }

  return (
    <div
      className="overflow-x-auto rounded-lg border border-[var(--border-default)] bg-[var(--bg-surface)] shadow-[var(--shadow-sm)]"
      aria-busy={busy || undefined}
    >
      <table className="w-full text-sm" aria-label={ariaLabel}>
        <thead className="bg-[var(--bg-muted)] text-[var(--text-secondary)]">
          <tr>
            {columns.map((col) => {
              const canSort = sortable && Boolean(col.sortAccessor);
              const active = canSort && sort?.key === col.key;
              const ariaSort = canSort
                ? active
                  ? sort?.dir === "asc"
                    ? "ascending"
                    : "descending"
                  : "none"
                : undefined;
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={ariaSort}
                  className={`px-4 py-2 text-left font-medium ${col.className ?? ""}`}
                >
                  {canSort ? (
                    <button
                      type="button"
                      onClick={() => {
                        toggleSort(setSort, sort, col.key);
                      }}
                      className={[
                        "inline-flex items-center gap-1 transition-colors",
                        "focus-visible:rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--bg-muted)]",
                        active ? "text-[var(--text-primary)]" : "hover:text-[var(--text-primary)]",
                      ].join(" ")}
                    >
                      <span>{col.header}</span>
                      <SortIcon active={active} dir={sort?.dir ?? null} />
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const interactive = Boolean(onRowClick);
            const isSelected = selectedKey !== null && rowKey(row) === selectedKey;
            return (
              // Zebra striping (odd / even) on the base layer; the hover and
              // focus-visible states override both with the indigo accent-soft
              // tint so the active row reads regardless of its parity. A
              // selected row keeps the accent tint + a left marker so it
              // stays anchored while its detail panel is open below.
              <tr
                key={rowKey(row)}
                aria-selected={isSelected || undefined}
                className={[
                  "border-t border-[var(--border-subtle)] transition-colors",
                  isSelected
                    ? "bg-[var(--bg-accent-soft)] shadow-[inset_2px_0_0_0_var(--accent)]"
                    : "odd:bg-[var(--bg-surface)] even:bg-[var(--bg-surface-2)] hover:bg-[var(--bg-accent-soft)]",
                  interactive
                    ? "cursor-pointer focus-visible:bg-[var(--bg-accent-soft)] focus-visible:outline-none"
                    : "",
                ].join(" ")}
                onClick={
                  onRowClick
                    ? () => {
                        onRowClick(row);
                      }
                    : undefined
                }
                onKeyDown={
                  onRowClick
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
                tabIndex={interactive ? 0 : undefined}
              >
                {columns.map((col) => (
                  <td key={col.key} className={`px-4 py-2 ${col.className ?? ""}`}>
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function toggleSort(
  setSort: (next: { key: string; dir: SortDir } | null) => void,
  current: { key: string; dir: SortDir } | null,
  key: string,
): void {
  if (current?.key !== key) {
    setSort({ key, dir: "desc" });
    return;
  }
  if (current.dir === "desc") {
    setSort({ key, dir: "asc" });
    return;
  }
  setSort(null); // third click clears
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir | null }) {
  if (!active) {
    return (
      <span className="inline-flex flex-col text-[var(--text-tertiary)]" aria-hidden>
        <ChevronUp className="-mb-0.5 size-2.5" />
        <ChevronDown className="size-2.5" />
      </span>
    );
  }
  return dir === "asc" ? (
    <ChevronUp className="size-3 text-[var(--text-primary)]" aria-hidden />
  ) : (
    <ChevronDown className="size-3 text-[var(--text-primary)]" aria-hidden />
  );
}

function normalise(v: string | number | Date | null | undefined): string | number | null {
  if (v === null || v === undefined) return null;
  if (v instanceof Date) return v.getTime();
  if (typeof v === "string" || typeof v === "number") return v;
  return String(v);
}
