import { floatPosition } from "@/lib/skin-float";

/** The five wear bands as a coloured bar with a marker at the item's float. */
export function SkinFloatBar({ value }: { value: number }) {
  return (
    <div className="relative h-1.5 w-full" aria-hidden>
      <div className="flex h-full overflow-hidden rounded-full">
        <span className="h-full bg-emerald-500" style={{ width: "7%" }} />
        <span className="h-full bg-lime-400" style={{ width: "8%" }} />
        <span className="h-full bg-yellow-400" style={{ width: "23%" }} />
        <span className="h-full bg-orange-400" style={{ width: "7%" }} />
        <span className="h-full flex-1 bg-red-500" />
      </div>
      <span
        className="bg-foreground absolute -top-1 h-3.5 w-0.5 rounded"
        style={{ left: `${String(floatPosition(value))}%` }}
      />
    </div>
  );
}
