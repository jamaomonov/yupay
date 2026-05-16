import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
  className?: string;
}

interface Props<T> {
  rows: T[];
  columns: Column<T>[];
  rowKey: (row: T) => string;
  empty?: string;
  onRowClick?: (row: T) => void;
}

export function DataTable<T>({ rows, columns, rowKey, empty, onRowClick }: Props<T>) {
  if (rows.length === 0) {
    return (
      <div className="rounded-lg border bg-[--color-bg] p-10 text-center text-sm text-[--color-muted]">
        {empty ?? "Пока пусто."}
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-lg border bg-[--color-bg]">
      <table className="w-full text-sm">
        <thead className="bg-[--color-subtle] text-[--color-muted]">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-2 text-left font-medium ${col.className ?? ""}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className="border-t transition-colors hover:bg-[--color-subtle]/60"
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              style={{ cursor: onRowClick ? "pointer" : undefined }}
            >
              {columns.map((col) => (
                <td key={col.key} className={`px-4 py-2 ${col.className ?? ""}`}>
                  {col.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
