import { Skeleton } from "@/components/ui/Skeleton";

/**
 * Placeholder for the order page while the order (and, for guests, the guest
 * token) is still loading.
 *
 * Mirrors `OrderStatus`'s real layout — back-link, status tile + heading,
 * summary rows, item rows — so the page doesn't visibly reflow when the data
 * lands. `aria-busy` on the wrapper tells assistive tech the region is loading
 * without narrating the individual boxes.
 */
export function OrderStatusSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true">
      <Skeleton className="h-4 w-28" />

      <div className="border-border bg-card space-y-5 rounded-2xl border p-5 sm:p-6">
        <div className="space-y-3">
          <Skeleton className="h-3 w-20" />
          <div className="flex items-start gap-3.5">
            <Skeleton className="size-11 shrink-0 rounded-xl" />
            <div className="min-w-0 flex-1 space-y-2 pt-1">
              <Skeleton className="h-5 w-2/5" />
              <Skeleton className="h-3.5 w-4/5" />
            </div>
          </div>
        </div>

        {/* Summary rows (total / paid with / dates). */}
        <div className="space-y-2.5">
          {[0, 1, 2].map((i) => (
            <div key={i} className="flex items-center justify-between gap-4">
              <Skeleton className="h-3.5 w-24" />
              <Skeleton className="h-3.5 w-20" />
            </div>
          ))}
        </div>

        {/* Item rows. */}
        <div className="space-y-3">
          <Skeleton className="h-3.5 w-28" />
          <div className="flex items-center gap-3">
            <Skeleton className="size-12 shrink-0 rounded-xl" />
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-3.5 w-1/2" />
              <Skeleton className="h-3 w-1/4" />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
