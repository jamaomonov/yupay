import { ArrowLeft } from "lucide-react";

/**
 * Extracted out of `OrderSuccess.tsx` (2026-09-03 review) purely to keep
 * that file near the repo's TS file-length budget — no behaviour change.
 */
export function SkeletonView({ onBack }: { onBack: () => void }) {
  return (
    <div className="space-y-4 pb-6">
      <header className="flex items-center gap-3 px-4 pt-3">
        <button
          onClick={onBack}
          className="flex size-9 items-center justify-center rounded-xl"
          style={{
            background: "hsl(var(--card))",
            border: "1px solid hsl(var(--border))",
          }}
        >
          <ArrowLeft size={15} className="text-white/60" />
        </button>
        <div
          className="h-3 flex-1 animate-pulse rounded"
          style={{ background: "hsl(var(--surface-2))" }}
        />
      </header>
      <div className="px-4">
        <div
          className="h-28 animate-pulse rounded-3xl"
          style={{ background: "hsl(var(--surface-1))" }}
        />
      </div>
      <div className="space-y-2 px-4">
        {Array.from({ length: 2 }).map((_, i) => (
          <div
            key={i}
            className="h-20 animate-pulse rounded-2xl"
            style={{ background: "hsl(var(--surface-1))" }}
          />
        ))}
      </div>
    </div>
  );
}
