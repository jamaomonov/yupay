/**
 * A brand's mark at list size: its logo, or its initial where there is none.
 *
 * Sits beside an order's title so a row reads as "PUBG" or "Roblox" at a
 * glance, before the words do — ten rows of monospace codes look alike,
 * ten game icons do not.
 */
export function BrandMark({
  name,
  logoUrl,
  size = "md",
}: {
  name: string | null;
  logoUrl: string | null;
  /** `sm` for a dense row, `md` for a title. */
  size?: "sm" | "md";
}) {
  const box = size === "sm" ? "h-7 w-7 text-xs" : "h-9 w-9 text-sm";
  return (
    <span
      aria-hidden
      className={`bg-card-2 border-border text-tx-dim flex shrink-0 items-center justify-center overflow-hidden rounded-lg border font-semibold ${box}`}
    >
      {logoUrl !== null ? (
        /* eslint-disable-next-line @next/next/no-img-element -- an
           operator-entered absolute URL, as in the catalog grid. */
        <img src={logoUrl} alt="" loading="lazy" className="h-full w-full object-cover" />
      ) : (
        (name ?? "").trim().charAt(0).toUpperCase()
      )}
    </span>
  );
}
