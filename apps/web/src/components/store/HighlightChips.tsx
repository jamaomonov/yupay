/**
 * Localized value-prop chips (Steam's "0% комиссии", "Оплата в сумах").
 *
 * Renders nothing when `items` is empty — callers pass `brand.highlights ?? []`
 * because an API response that predates the field omits it entirely.
 *
 * Two surfaces, hence `variant`. The brand hero puts them over a photograph, so
 * there they are a translucent black pill with white text and a blur; the Steam
 * gifts hub has no hero image, and those same styles there are white-on-white
 * in the light theme. The choice is the caller's because only the caller knows
 * what is behind them.
 */
export function HighlightChips({
  items,
  variant = "on-image",
}: {
  items: string[];
  /** `on-image` over a hero photo, `on-surface` over the page background. */
  variant?: "on-image" | "on-surface";
}) {
  if (items.length === 0) return null;
  const chip =
    variant === "on-image"
      ? "border-border-2/70 bg-black/45 text-white/85 backdrop-blur"
      : "border-border bg-card text-tx-mute";
  return (
    <>
      {items.map((h) => (
        <span
          key={h}
          className={`inline-flex items-center gap-2 whitespace-nowrap rounded-full border px-3.5 py-2 text-[13px] ${chip}`}
        >
          <span className="bg-primary size-[5px] shrink-0 rounded-full" aria-hidden="true" />
          {h}
        </span>
      ))}
    </>
  );
}
