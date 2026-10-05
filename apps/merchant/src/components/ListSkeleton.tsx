/**
 * The shape of a list that has not answered yet.
 *
 * Every list screen rendered *nothing* between mount and its first page —
 * the same blank a lapsed session shows — so for a second a reseller could
 * not tell "loading" from "broken". Grey bars in the rows' own layout say
 * the screen is there and the data is on its way.
 */
export function ListSkeleton({ rows = 5, className = "" }: { rows?: number; className?: string }) {
  return (
    <div
      aria-busy
      className={`border-border bg-card divide-border animate-pulse divide-y rounded-xl border ${className}`}
    >
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center justify-between gap-4 px-4 py-3.5">
          <div className="min-w-0 flex-1 space-y-2">
            <div className="bg-card-2 h-3.5 w-1/3 rounded" />
            <div className="bg-card-2 h-3 w-1/5 rounded" />
          </div>
          <div className="bg-card-2 h-3.5 w-14 rounded" />
        </div>
      ))}
    </div>
  );
}
