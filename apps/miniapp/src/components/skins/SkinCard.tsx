import { isVanilla, rarityGlow, steamImageSize } from "@yupay/utils";
import { Link } from "wouter";

import type { SkinItem } from "@yupay/utils";

import { SafeImage } from "@/components/ui/safe-image";
import { useT } from "@/lib/i18n";
import { skinPriceText } from "@/lib/skins";

/**
 * One catalogue tile. The rarity colour runs along the bottom edge — how the
 * game and every CS2 market mark rarity, so it reads at a glance.
 */
export function SkinCard({ item }: { item: SkinItem }) {
  const { t } = useT();
  const price = skinPriceText(item.price_uzs, item.price_usd);
  // Under 5 % a badge on every other card only dilutes the ones that matter.
  const discount =
    item.discount_percent !== null && item.discount_percent >= 5 ? item.discount_percent : null;
  const glow = rarityGlow(item.rarity_color);

  return (
    <Link
      href={`/cs2-market/${item.slug}`}
      className="flex flex-col overflow-hidden rounded-2xl border"
      style={{
        borderColor: "hsl(var(--border))",
        background: "hsl(var(--surface-2))",
      }}
    >
      <div className="relative aspect-[4/3] w-full overflow-hidden bg-black/20">
        {glow && <span aria-hidden className="absolute inset-0" style={{ background: glow }} />}
        {item.image_url && (
          <SafeImage
            src={steamImageSize(item.image_url, "256fx256f")}
            alt={item.name}
            className="relative h-full w-full object-contain p-2"
          />
        )}
        {discount !== null && (
          <span className="bg-primary absolute right-2 top-2 rounded-full px-2 py-0.5 text-[10px] font-bold text-black">
            {t("cs2.discount", { percent: discount })}
          </span>
        )}
      </div>
      <div className="flex flex-1 flex-col gap-0.5 p-2.5">
        <div className="flex items-center gap-1.5 text-[10px] text-white/50">
          {item.stattrak && <span className="font-semibold text-orange-400">StatTrak™</span>}
          {item.souvenir && <span className="font-semibold text-yellow-400">Souvenir</span>}
          {item.weapon && <span className="truncate">{item.weapon}</span>}
          {item.exterior && <span className="ml-auto font-mono">{item.exterior}</span>}
        </div>
        <p className="line-clamp-2 text-[12px] font-semibold leading-snug text-white">
          {isVanilla(item) ? t("cs2.vanilla") : (item.skin ?? item.name)}
          {item.phase && <span className="font-normal text-white/50"> · {item.phase}</span>}
        </p>
        <p className="mt-auto pt-1 text-[13px] font-bold tabular-nums text-white">
          {price ?? <span className="font-sans text-[11px] text-white/50">{t("cs2.soldOut")}</span>}
        </p>
      </div>
    </Link>
  );
}
