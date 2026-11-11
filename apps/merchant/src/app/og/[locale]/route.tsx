/**
 * The link preview for the reseller site — `/og/<locale>`, 1200×630 PNG.
 *
 * Resellers share links inside Telegram, where a link with no picture looks
 * like spam. The card carries the mark, the hero line in the reader's
 * language and the catalogue size — the same three things the landing's
 * first screen says.
 *
 * Lives outside `[locale]` (and outside the i18n middleware, see
 * `middleware.ts`) so the URL is the same shape for every locale and never
 * redirected: `ru` has no path prefix on the site, and a chat crawler should
 * not have to follow a 308 to reach a picture. Wired into every page's
 * metadata by `social()` in `lib/seo.ts`.
 *
 * Rendered per request and cached at the edge for a day: the card changes
 * only when the copy does, and a static prerender would put a font read on
 * the build's critical path.
 */

import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";
import { hasLocale } from "next-intl";
import { getTranslations } from "next-intl/server";

import { routing } from "@/i18n/routing";
import { CATALOG_BRANDS, CATALOG_SKUS, formatCount } from "@/lib/brands";
import { OG_IMAGE_SIZE } from "@/lib/seo";

/** Brand colours — `--bg` and `--primary` of the dark theme in `globals.css`. */
const BG = "#080a17";
const LIME = "#bbff33";
const TEXT = "#f2f4f8";
const MUTED = "#aab2c5";

/**
 * The link-preview fonts (Unbounded Black, Inter SemiBold, both OFL —
 * licences beside them), the same files as `apps/web/assets/og`. A copy, not
 * a cross-app read: the dev container mounts only this app, and a card that
 * renders in production but 500s locally is one nobody checks. Satori bundles
 * a Latin-only default, so without these the RU and UZ cards would render
 * boxes.
 */
const FONTS = join(process.cwd(), "assets", "og");

let fonts: Promise<{ unbounded: Buffer; inter: Buffer }> | null = null;

function loadFonts(): Promise<{ unbounded: Buffer; inter: Buffer }> {
  fonts ??= Promise.all([
    readFile(join(FONTS, "Unbounded-Black.ttf")),
    readFile(join(FONTS, "Inter-SemiBold.ttf")),
  ])
    .then(([unbounded, inter]) => ({ unbounded, inter }))
    .catch((err: unknown) => {
      // Not cached: a transient read error must not poison every later card.
      fonts = null;
      throw err;
    });
  return fonts;
}

/** The YuPay mark — the same path as `components/Mark.tsx`. */
const MARK =
  "M0.06 23.83l0 294.05c0,0 -5.53,87.63 88.85,108.37l230.68 0c0,0 68.19,-17.67 80.63,-88.17l0 -210.84 71.58 0 -57.83 -63.63 -57.83 -63.63 -57.83 63.63 -57.83 63.63 71.57 0 0 183.78c0,0 -5.1,27.06 -30.74,27.06l-167.01 0c0,0 -26.08,-1.43 -26.08,-20.21l0 -294.05 -88.17 0z";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ locale: string }> },
): Promise<Response> {
  const { locale } = await params;
  if (!hasLocale(routing.locales, locale)) return new Response(null, { status: 404 });

  const t = await getTranslations({ locale, namespace: "merchant.landing" });
  const { unbounded, inter } = await loadFonts();
  const metrics = `${formatCount(locale, CATALOG_BRANDS)}+ ${t("metricBrands")} · ${formatCount(locale, CATALOG_SKUS)}+ ${t("metricSkus")}`;

  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        padding: "64px 72px",
        backgroundColor: BG,
        backgroundImage:
          "radial-gradient(circle at 88% 12%, rgba(187,255,51,0.22) 0%, rgba(8,10,23,0) 55%)",
        color: TEXT,
        fontFamily: "Inter",
      }}
    >
      <div style={{ display: "flex", alignItems: "center" }}>
        <svg width="56" height="51" viewBox="0 0 471.8 426.26">
          <path fill={LIME} d={MARK} />
        </svg>
        <div style={{ display: "flex", marginLeft: 20, fontFamily: "Unbounded", fontSize: 40 }}>
          YuPay
        </div>
        <div
          style={{
            display: "flex",
            marginLeft: 18,
            padding: "6px 16px",
            border: `2px solid ${LIME}`,
            borderRadius: 999,
            color: LIME,
            fontSize: 24,
          }}
        >
          Reseller
        </div>
      </div>

      <div
        style={{
          display: "flex",
          fontFamily: "Unbounded",
          fontSize: 54,
          lineHeight: 1.18,
          maxWidth: 1040,
        }}
      >
        {t("heading")}
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", color: LIME, fontSize: 32 }}>{metrics}</div>
        <div style={{ display: "flex", marginTop: 14, color: MUTED, fontSize: 24 }}>
          {`${t("metricCheck")} · ${t("metricAuto")} · reseller.yupay.uz`}
        </div>
      </div>
    </div>,
    {
      ...OG_IMAGE_SIZE,
      fonts: [
        { name: "Unbounded", data: unbounded, weight: 900, style: "normal" },
        { name: "Inter", data: inter, weight: 600, style: "normal" },
      ],
      headers: {
        "Cache-Control": "public, max-age=86400, s-maxage=86400, stale-while-revalidate=604800",
      },
    },
  );
}
