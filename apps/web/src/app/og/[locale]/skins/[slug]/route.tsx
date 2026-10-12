/**
 * Link-preview card for a CS2 skin page — `/og/<locale>/skins/<slug>`.
 *
 * The weapon small, the finish large, the item on a glow of its rarity
 * colour and the lowest price in soʻm: what a buyer pasting a link into a
 * chat wants the other side to see. Outside `[locale]` for the same reason
 * as the brand card (see `store/[brandSlug]/route.tsx`).
 */

import { isVanilla } from "@yupay/utils";
import { ImageResponse } from "next/og";
import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";

import type { SkinCategory } from "@/lib/skins";

import { routing } from "@/i18n/routing";
import {
  Glow,
  headlineSize,
  OG_HEADERS,
  OG_SIZE,
  ogAssets,
  OgFrame,
  PriceChip,
  remoteImage,
} from "@/lib/og-image";
import { steamImageSize } from "@/lib/skin-float";
import { displayPrice, getSkinDetail } from "@/lib/skins";

const HEX = /^#[0-9a-f]{6}$/i;

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ locale: string; slug: string }> },
) {
  const { locale, slug } = await params;
  if (!hasLocale(routing.locales, locale)) return new Response(null, { status: 404 });
  const item = await getSkinDetail(locale, slug);
  if (item === null) return new Response(null, { status: 404 });
  const t = await getTranslations({ locale, namespace: "web.skins" });

  // "Souvenir AWP | Dragon Lore (Minimal Wear)" → "Souvenir AWP" over "DRAGON LORE".
  // A name with no " | " (sticker, case, agent) is its own headline under its category.
  const [head, finish] = item.name.replace(/\s*\([^)]*\)\s*$/, "").split(" | ");
  const headline = isVanilla(item)
    ? t("vanilla")
    : [finish ?? head ?? item.name, item.phase].filter(Boolean).join(" ");
  const label = finish ? head : t(`category.${item.category as SkinCategory}`); // one of SKIN_CATEGORIES
  const wear = item.exterior ? t(`exterior.${item.exterior}`) : null;
  const price = item.count > 0 ? displayPrice(locale, item.price_uzs, item.price_usd) : null;
  const glow = item.rarity_color && HEX.test(item.rarity_color) ? item.rarity_color : "#4b69ff";

  const [{ fonts, wordmark, payMarks }, art] = await Promise.all([
    ogAssets(),
    remoteImage(item.image_url ? steamImageSize(item.image_url, "512fx384f") : null, 750),
  ]);

  return new ImageResponse(
    <OgFrame wordmark={wordmark} payMarks={payMarks}>
      <Glow x={70} y={48} color={`${glow}77`} reach={42} />
      {art && (
        // eslint-disable-next-line @next/next/no-img-element -- Satori
        <img
          src={art}
          width={680}
          height={510}
          style={{ position: "absolute", right: 30, top: 50, objectFit: "contain" }}
          alt=""
        />
      )}
      <div
        style={{
          position: "absolute",
          left: 48,
          bottom: 130,
          width: 640,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {label && (
          <div style={{ fontFamily: "Unbounded", fontSize: 30, color: "#cfd5e1" }}>{label}</div>
        )}
        <div
          style={{
            fontFamily: "Unbounded",
            fontSize: headlineSize(headline, [78, 60, 46]),
            lineHeight: 1.05,
            marginTop: 8,
            textTransform: "uppercase",
          }}
        >
          {headline}
        </div>
        {wear && <div style={{ fontSize: 26, color: "#cfd5e1", marginTop: 12 }}>{wear}</div>}
        {price && (
          <div style={{ display: "flex", marginTop: 22 }}>
            <PriceChip>{t("fromPrice", { price })}</PriceChip>
          </div>
        )}
      </div>
    </OgFrame>,
    { ...OG_SIZE, fonts, headers: OG_HEADERS },
  );
}
