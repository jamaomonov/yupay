import { Skeleton } from "@/components/ui/Skeleton";

/**
 * Placeholder shaped like a real order card (`OrderCard` / `GuestOrderCard`):
 * 44px thumbnail tile, title line, meta line. Shared by the account order list
 * and the guest card's own loading state so both load the same way.
 */
export function OrderCardSkeleton() {
  return (
    <div
      className="border-border bg-card flex items-center gap-3 rounded-2xl border p-3.5"
      aria-hidden="true"
    >
      <Skeleton className="h-11 w-11 shrink-0 rounded-xl" />
      <div className="min-w-0 flex-1 space-y-2">
        <Skeleton className="h-3.5 w-2/5" />
        <Skeleton className="h-3 w-1/4" />
      </div>
    </div>
  );
}

/** A short stack of card skeletons for list-level loading states. */
export function OrderListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <ul className="space-y-3" aria-busy="true">
      {Array.from({ length: rows }, (_, i) => (
        <li key={i}>
          <OrderCardSkeleton />
        </li>
      ))}
    </ul>
  );
}
