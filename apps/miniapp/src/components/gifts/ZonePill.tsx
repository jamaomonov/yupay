import { useT } from "@/lib/i18n";

/**
 * Region pill for the zone/region step — disabled (with a title tooltip)
 * when the currently selected package doesn't price this zone.
 *
 * Extracted out of `GiftGame.tsx` (2026-09-03 review) purely to keep that
 * file near the repo's TS file-length budget — no behaviour change.
 */
export function ZonePill({
  zone,
  active,
  available,
  onSelect,
}: {
  zone: string;
  active: boolean;
  available: boolean;
  onSelect: () => void;
}) {
  const { t } = useT();
  return (
    <button
      type="button"
      disabled={!available}
      title={available ? undefined : t("gifts.game.noPriceInRegion")}
      aria-pressed={active}
      onClick={onSelect}
      className="rounded-full border px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-40"
      style={{
        borderColor: active ? "hsl(var(--primary))" : "hsl(var(--border))",
        background: active ? "hsl(var(--primary) / 0.12)" : "transparent",
        color: active ? "hsl(var(--primary))" : "rgba(255,255,255,0.6)",
      }}
    >
      {zone}
    </button>
  );
}
