import { rarityGlow, steamImageSize, wearColor } from "@yupay/utils";
import { Eye } from "lucide-react";

import type { SkinDetail, SkinListing } from "@yupay/utils";

import { SkinFloatBar } from "@/components/skins/SkinFloatBar";
import { SafeImage } from "@/components/ui/safe-image";
import { useT } from "@/lib/i18n";
import { openExternalLink } from "@/lib/telegram";

/**
 * The item's picture as the offer the buyer picked: its float on the wear bar with the
 * wear code in one corner, inspect in game in the other, its stickers along the bottom.
 * Mirrors the web's `SkinHero`.
 */
export function SkinHeroCard({ item, offer }: { item: SkinDetail; offer: SkinListing | null }) {
  const { t } = useT();
  const float = offer?.float_value ?? null;
  const stickers = offer?.stickers ?? [];
  const inspect = offer?.inspect_url?.startsWith("steam://") ? offer.inspect_url : null;
  const glow = rarityGlow(item.rarity_color);
  const panel = { background: "hsl(var(--background) / 0.72)", backdropFilter: "blur(6px)" };

  return (
    <div
      className="relative aspect-[4/3] w-full overflow-hidden rounded-2xl border border-b-[3px]"
      style={{
        borderColor: "hsl(var(--border))",
        background: "hsl(var(--surface-2))",
        ...(item.rarity_color ? { borderBottomColor: item.rarity_color } : {}),
      }}
    >
      {glow && <span aria-hidden className="absolute inset-0" style={{ background: glow }} />}
      {item.image_url && (
        <SafeImage
          src={steamImageSize(item.image_url, "512fx384f")}
          alt={item.name}
          className="h-full w-full object-contain px-6 py-10"
        />
      )}

      {inspect && (
        <button
          type="button"
          aria-label={t("cs2.inspect")}
          onClick={() => {
            openExternalLink(inspect);
          }}
          className="absolute left-2.5 top-2.5 flex h-9 w-9 items-center justify-center rounded-lg text-white/80"
          style={panel}
        >
          <Eye className="h-4 w-4" aria-hidden="true" />
        </button>
      )}

      {(float !== null || item.exterior) && (
        <div className="absolute right-2.5 top-2.5 w-32 rounded-lg px-2 py-1.5" style={panel}>
          <div className="mb-1 flex items-baseline justify-between gap-2 text-[11px]">
            <span className="tabular-nums text-white/85">
              {float !== null ? float.toFixed(4) : t("cs2.float")}
            </span>
            {item.exterior && (
              <span className="font-bold" style={{ color: wearColor(item.exterior) ?? undefined }}>
                {item.exterior}
              </span>
            )}
          </div>
          {float !== null && <SkinFloatBar value={float} />}
        </div>
      )}

      {stickers.length > 0 && (
        <ul className="absolute inset-x-2.5 bottom-2.5 flex gap-1.5" aria-label={t("cs2.stickers")}>
          {stickers.map((s, i) => (
            <li
              key={`${String(i)}-${s.name}`}
              className="flex h-10 w-10 items-center justify-center rounded-lg"
              style={panel}
            >
              {s.image ? (
                <img src={s.image} alt={s.name} className="h-8 w-8 object-contain" />
              ) : (
                <span role="img" aria-label={s.name} className="h-6 w-6 rounded bg-white/10" />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
