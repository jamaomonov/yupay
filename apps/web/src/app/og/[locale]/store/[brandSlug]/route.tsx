/**
 * Link-preview card for a brand page — `/og/<locale>/store/<slug>`.
 *
 * Lives outside `[locale]` (and outside the i18n middleware, see
 * `middleware.ts`) so the URL is the same for every locale and never
 * redirected: `ru` has no path prefix on the site, and a chat crawler
 * should not have to follow a 308 to reach a picture.
 */

import { ImageResponse } from "next/og";
import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";

import { routing } from "@/i18n/routing";
import { getBrandDetail, getProductDetail, type ProductDetail } from "@/lib/catalog";
import {
  headlineSize,
  OG_HEADERS,
  OG_SIZE,
  ogAssets,
  OgFrame,
  PriceChip,
  remoteImage,
} from "@/lib/og-image";
import { formatUzs } from "@/lib/seo";

const CURRENCY = "UZS";

/** What fits on one line of the sub-heading at its size, in characters. */
const LINE_BUDGET = 34;

/** A product name short enough to share the line with others. */
const SHORT_NAME = 22;

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ locale: string; brandSlug: string }> },
) {
  const { locale, brandSlug } = await params;
  if (!hasLocale(routing.locales, locale)) return new Response(null, { status: 404 });
  // Same URLs (and so the same Data-Cache entries) as the brand page itself.
  const brand = await getBrandDetail(brandSlug, locale, CURRENCY);
  if (!brand) return new Response(null, { status: 404 });
  const products = (
    await Promise.all((brand.products ?? []).map((p) => getProductDetail(p.slug, locale, CURRENCY)))
  ).filter((p): p is ProductDetail => p !== null);

  // Fixed-price SKUs only: a per-star or typed-amount SKU has a rate, and
  // «от 204 сум» on a card would read as the price of the purchase.
  const prices = products
    .flatMap((p) => p.skus)
    .filter((s) => !s.variable_amount && !s.min_qty && s.display_price)
    .map((s) => Math.round(Number(s.display_price?.amount)))
    .filter((n) => n > 0);
  const t = await getTranslations({ locale, namespace: "web.skins" });
  const price = prices.length
    ? t("fromPrice", { price: formatUzs(locale, Math.min(...prices)) })
    : null;
  // Product names that fit one line, in catalogue order, minus the brand's own
  // name. Short names first: one long one («WOW Coins — режим World of
  // Wonder») would otherwise take the whole line from «UC · Prime».
  const names = products.map((p) => p.name).filter((n) => !brand.name.includes(n));
  const short = names.filter((n) => n.length <= SHORT_NAME);
  const line = (short.length ? short : names)
    .reduce<string[]>((kept, n) => {
      const next = [...kept, n];
      return next.join(" · ").length <= LINE_BUDGET ? next : kept;
    }, [])
    .join(" · ");

  const [{ fonts, wordmark, payMarks }, hero, logo] = await Promise.all([
    ogAssets(),
    remoteImage(brand.hero_image_url, 1200),
    remoteImage(brand.logo_url, 128),
  ]);

  return new ImageResponse(
    <OgFrame
      wordmark={wordmark}
      payMarks={payMarks}
      backdrop={
        <>
          {hero && (
            // eslint-disable-next-line @next/next/no-img-element -- Satori
            <img
              src={hero}
              width={840}
              height={630}
              style={{ position: "absolute", left: 360, top: 0, objectFit: "cover" }}
              alt=""
            />
          )}
          {/* Fades the art into the card behind the text column. */}
          <div
            style={{
              position: "absolute",
              left: 360,
              top: 0,
              width: 420,
              height: 630,
              display: "flex",
              background: "linear-gradient(to right, #0b0d12, rgba(11,13,18,0))",
            }}
          />
        </>
      }
    >
      <div
        style={{
          position: "absolute",
          left: 48,
          top: 150,
          width: 520,
          display: "flex",
          flexDirection: "column",
        }}
      >
        {logo && (
          // eslint-disable-next-line @next/next/no-img-element -- Satori
          <img src={logo} width={64} height={64} style={{ borderRadius: 16 }} alt="" />
        )}
        <div
          style={{
            fontFamily: "Unbounded",
            fontSize: headlineSize(brand.name, [72, 56, 44]),
            lineHeight: 1.05,
            marginTop: 20,
          }}
        >
          {brand.name}
        </div>
        {line && <div style={{ fontSize: 26, color: "#cfd5e1", marginTop: 14 }}>{line}</div>}
        {price && (
          <div style={{ display: "flex", marginTop: 26 }}>
            <PriceChip>{price}</PriceChip>
          </div>
        )}
      </div>
    </OgFrame>,
    { ...OG_SIZE, fonts, headers: OG_HEADERS },
  );
}
