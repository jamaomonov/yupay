import type { LucideIcon } from "lucide-react";

/**
 * Nothing here yet, said with a shape rather than a sentence alone.
 *
 * A bare line of grey text is easy to misread as a screen that failed to
 * load — which in a cabinet where every read can 401 is exactly the wrong
 * guess. The framed panel says "this rendered, and it is empty".
 */
export function EmptyState({
  icon: Icon,
  title,
  hint,
}: {
  icon: LucideIcon;
  title: string;
  /** Optional second line: what to do about it, when there is something. */
  hint?: string;
}) {
  return (
    <div className="border-border mt-8 flex flex-col items-center rounded-xl border border-dashed px-6 py-12 text-center">
      <span className="text-tx-dim" aria-hidden="true">
        <Icon size={26} strokeWidth={1.5} />
      </span>
      <p className="text-tx-mute mt-3 text-sm">{title}</p>
      {hint !== undefined && <p className="text-tx-dim mt-1 text-[12.5px]">{hint}</p>}
    </div>
  );
}
