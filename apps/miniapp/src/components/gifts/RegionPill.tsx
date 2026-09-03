import { countryName, flagEmoji } from "@/lib/regions";
import { useT } from "@/lib/i18n";

/**
 * Country pill for the region step — flag + localized name, priced from the
 * zone that covers it (`zoneForCountry`, `@/lib/gifts`). Disabled *with
 * visible text* (not a `title=` tooltip, which is invisible on a
 * touchscreen) when the currently selected package has no price in that
 * country's zone.
 *
 * Renamed from `ZonePill` (2026-09-03): the wire/pricing unit is still the
 * zone, but the buyer now picks a concrete country — mirrors
 * `apps/web/src/components/gifts/GiftPurchasePanel.tsx::CountryButton` on
 * the web storefront, adapted to this app's inline-style pill convention.
 */
export function RegionPill({
  country,
  active,
  available,
  locale,
  onSelect,
}: {
  country: string;
  active: boolean;
  available: boolean;
  locale: string;
  onSelect: () => void;
}) {
  const { t } = useT();
  return (
    <button
      type="button"
      disabled={!available}
      aria-pressed={active}
      onClick={onSelect}
      className="flex flex-col items-start gap-0.5 rounded-xl border px-3 py-1.5 text-left text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
      style={{
        borderColor: active ? "hsl(var(--primary))" : "hsl(var(--border))",
        background: active ? "hsl(var(--primary) / 0.12)" : "transparent",
        color: active ? "hsl(var(--primary))" : "rgba(255,255,255,0.6)",
      }}
    >
      <span className="inline-flex items-center gap-1.5">
        <span aria-hidden="true">{flagEmoji(country)}</span>
        {countryName(country, locale)}
      </span>
      {!available && (
        <span className="text-[10px] font-normal normal-case text-white/40">
          {t("gifts.game.noPriceInRegion")}
        </span>
      )}
    </button>
  );
}
