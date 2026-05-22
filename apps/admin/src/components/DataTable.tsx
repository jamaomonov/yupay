import { useMemo, useState, type ReactNode } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";

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
  onRowClick?: (row: T) => void;
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
  onRowClick,
  sortable = true,
}: Props<T>) {
  const [sort, setSort] = useState<{ key: string; dir: SortDir } | null>(null);

  const sorted = useMemo(() => {
    if (!sort || !sortable) return rows;
    const col = columns.find((c) => c.key === sort.key && c.sortAccessor);
    if (!col || !col.sortAccessor) return rows;
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
    return (
      <div className="rounded-lg border bg-[--color-bg] p-10 text-center text-sm text-[--color-muted]">
        {empty ?? "Пока пусто."}
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border bg-[--color-bg]">
      <table className="w-full text-sm">
        <thead className="bg-[--color-subtle] text-[--color-muted]">
          <tr>
            {columns.map((col) => {
              const canSort = sortable && Boolean(col.sortAccessor);
              const active = canSort && sort?.key === col.key;
              return (
                <th
                  key={col.key}
                  className={`px-4 py-2 text-left font-medium ${col.className ?? ""}`}
                >
                  {canSort ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(setSort, sort, col.key)}
                      className={[
                        "inline-flex items-center gap-1 transition-colors",
                        active ? "text-[--color-fg]" : "hover:text-[--color-fg]",
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
            return (
              <tr
                key={rowKey(row)}
                className={[
                  "border-t border-[--border-subtle] transition-colors hover:bg-[--bg-surface-2]",
                  interactive
                    ? "cursor-pointer focus-visible:bg-[--bg-accent-soft] focus-visible:outline-none"
                    : "",
                ].join(" ")}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
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
      <span className="inline-flex flex-col text-[--color-muted]/50">
        <ChevronUp className="size-2.5 -mb-0.5" />
        <ChevronDown className="size-2.5" />
      </span>
    );
  }
  return dir === "asc" ? (
    <ChevronUp className="size-3 text-[--color-fg]" />
  ) : (
    <ChevronDown className="size-3 text-[--color-fg]" />
  );
}

function normalise(
  v: string | number | Date | null | undefined,
): string | number | null {
  if (v === null || v === undefined) return null;
  if (v instanceof Date) return v.getTime();
  if (typeof v === "string" || typeof v === "number") return v;
  return String(v);
}
