import { Check } from "lucide-react";

/**
 * Localized value-prop chips shown in the brand hero (e.g. Steam's
 * "0% комиссии", "Оплата в сумах"). Renders nothing when `items` is empty —
 * callers pass `brand.highlights ?? []` since older/older-prerendering API
 * responses may omit the field entirely.
 */
export function HighlightChips({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      {items.map((h) => (
        <span
          key={h}
          className="border-primary/40 bg-primary/10 inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[12px] font-semibold text-white backdrop-blur"
        >
          <Check size={13} className="text-primary shrink-0" />
          {h}
        </span>
      ))}
    </>
  );
}
