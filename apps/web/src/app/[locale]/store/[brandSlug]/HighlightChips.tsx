/**
 * Localized value-prop chips shown in the brand hero (e.g. Steam's
 * "0% комиссии", "Оплата в сумах"). A small lime dot leads each label — the
 * hero-banner style from the design reference. Renders nothing when `items`
 * is empty — callers pass `brand.highlights ?? []` since older/older-
 * prerendering API responses may omit the field entirely.
 */
export function HighlightChips({ items }: { items: string[] }) {
  if (items.length === 0) return null;
  return (
    <>
      {items.map((h) => (
        <span
          key={h}
          className="border-border-2/70 inline-flex items-center gap-2 whitespace-nowrap rounded-full border bg-black/45 px-3.5 py-2 text-[13px] text-white/85 backdrop-blur"
        >
          <span className="bg-primary size-[5px] shrink-0 rounded-full" aria-hidden="true" />
          {h}
        </span>
      ))}
    </>
  );
}
