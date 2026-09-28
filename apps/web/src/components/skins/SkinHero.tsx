"use client";

import { steamImageSize, wearColor } from "@yupay/utils";
import { Eye } from "lucide-react";
import Image from "next/image";
import { useTranslations } from "next-intl";

import { SkinFloatBar } from "./SkinFloatBar";
import { useSelectedOffer } from "./SkinOffers";

import { isOptimizable } from "@/lib/image";

/**
 * The item's picture as the offer the buyer picked: its float on the wear bar and the
 * wear code in the corner, its stickers along the bottom, inspect in game in the other
 * corner — what a market shows before a price is paid (avan, skinsavdo).
 */
export function SkinHero({
  image,
  name,
  exterior,
  rarityColor,
}: {
  image: string | null;
  name: string;
  exterior: string | null;
  rarityColor: string | null;
}) {
  const t = useTranslations("web.skins");
  const { selected } = useSelectedOffer();
  const float = selected?.float_value ?? null;
  const stickers = selected?.stickers ?? [];
  const inspect = selected?.inspect_url?.startsWith("steam://") ? selected.inspect_url : null;

  return (
    <div
      className="bg-muted relative aspect-[4/3] overflow-hidden rounded-xl border-b-[3px] border-transparent"
      style={rarityColor ? { borderBottomColor: rarityColor } : undefined}
    >
      {image && (
        <Image
          src={steamImageSize(image, "512fx384f")}
          alt={name}
          fill
          priority
          unoptimized={!isOptimizable(image)}
          sizes="(min-width: 768px) 50vw, 100vw"
          className="object-contain p-8"
        />
      )}

      {inspect && (
        <a
          href={inspect}
          aria-label={t("inspect")}
          title={t("inspect")}
          className="bg-background/70 text-tx-mute hover:text-foreground absolute left-3 top-3 inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px] font-semibold backdrop-blur"
        >
          <Eye className="h-4 w-4" aria-hidden />
          <span className="hidden sm:inline">{t("inspect")}</span>
        </a>
      )}

      {(float !== null || exterior) && (
        <div className="bg-background/70 absolute right-3 top-3 w-40 rounded-lg px-2.5 py-2 backdrop-blur">
          <div className="mb-1.5 flex items-baseline justify-between gap-2 text-[12px]">
            <span className="tabular-nums">{float !== null ? float.toFixed(4) : t("float")}</span>
            {exterior && (
              <span className="font-bold" style={{ color: wearColor(exterior) ?? undefined }}>
                {exterior}
              </span>
            )}
          </div>
          {float !== null && <SkinFloatBar value={float} />}
        </div>
      )}

      {stickers.length > 0 && (
        <ul className="absolute inset-x-3 bottom-3 flex gap-2" aria-label={t("stickers")}>
          {stickers.map((s, i) => (
            <li
              key={`${String(i)}-${s.name}`}
              className="bg-background/70 flex size-12 items-center justify-center rounded-lg backdrop-blur sm:size-14"
              title={s.name}
            >
              {s.image ? (
                // Steam CDN sticker thumbnails: next/image adds nothing here.
                // eslint-disable-next-line @next/next/no-img-element
                <img src={s.image} alt={s.name} className="size-10 object-contain sm:size-12" />
              ) : (
                <span role="img" aria-label={s.name} className="bg-muted size-8 rounded" />
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
