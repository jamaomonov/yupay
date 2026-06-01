import { ArrowRight } from "lucide-react";
import Image from "next/image";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

/**
 * Bento-grid catalog teaser — one feature card spanning two rows + four
 * smaller brand cards, each backed by the real key-art used inside the mini
 * app (so web and in-app catalogs look like the same product). A dark
 * bottom-up gradient keeps the copy legible over the art.
 *
 * Card art/route metadata lives here; all copy (name/eyebrow/tag + the
 * feature stats) is read from web.catalog.cards.<slug>.* so EN/UZ stay at
 * parity. The list is hardcoded until /catalog API is wired; the shape
 * mirrors the live `Brand` type so the swap is a one-liner later.
 */
interface BentoCard {
  /** doubles as the i18n key under web.catalog.cards */
  slug: string;
  tagTone: "lime" | "blue" | "white" | "red";
  /** background key-art in /public/brands */
  bg: string;
  /** small square brand mark overlaid top-right (optional) */
  icon?: string;
}

const TAG_TONE: Record<BentoCard["tagTone"], string> = {
  lime: "bg-primary text-primary-foreground",
  blue: "bg-blue text-white",
  white: "bg-white text-black",
  red: "bg-[#FF5C39] text-white",
};

const CARDS: BentoCard[] = [
  { slug: "steam", tagTone: "lime", bg: "/brands/steam-bg.jpg" },
  {
    slug: "pubg-mobile",
    tagTone: "lime",
    bg: "/brands/pubg-bg.png",
    icon: "/brands/pubg-icon.svg",
  },
  {
    slug: "telegram-premium",
    tagTone: "red",
    bg: "/brands/telegram-bg.jpg",
    icon: "/brands/telegram-icon.webp",
  },
  { slug: "delta-force", tagTone: "white", bg: "/brands/deltaforce.webp" },
  {
    slug: "arena-breakout",
    tagTone: "blue",
    bg: "/brands/arenabreakout-bg.png",
    icon: "/brands/arenabreakout-icon.svg",
  },
];

/** Feature (Steam) card stats — label + value keys under web.catalog. */
const FEATURE_STATS: { labelKey: string; valueKey: string; lime?: boolean }[] = [
  { labelKey: "commission", valueKey: "cards.steam.statCommission" },
  { labelKey: "speed", valueKey: "cards.steam.statSpeed", lime: true },
  { labelKey: "rating", valueKey: "cards.steam.statRating" },
];

export async function CatalogBento({ locale }: { locale: string }) {
  const t = await getTranslations("web.catalog");
  const prefix = `/${locale}`;

  return (
    <section id="catalog" className="relative py-28">
      <div className="mx-auto max-w-[1200px] px-6 sm:px-10">
        <div className="mb-14 flex items-end justify-between gap-6">
          <div>
            <div className="text-primary font-mono text-xs font-semibold uppercase tracking-[0.16em]">
              [ 01 / {t("eyebrow")} ]
            </div>
            <h2 className="font-display mt-3 text-[clamp(2.2rem,4vw,3.4rem)] font-extrabold leading-[0.98] tracking-[-0.04em]">
              <span className="block">{t("titleLine1")}</span>
              <span className="text-tx-mute block">{t("titleLine2")}</span>
            </h2>
          </div>
          <Link
            href={`${prefix}/store`}
            className="border-border-2 text-foreground hover:border-tx-dim hover:bg-muted hidden h-[44px] items-center gap-2 rounded-[12px] border px-5 text-sm font-semibold transition sm:inline-flex"
          >
            {t("viewAll")}
            <ArrowRight size={14} strokeWidth={2.4} />
          </Link>
        </div>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-3 md:grid-rows-[320px_320px]">
          {CARDS.map((card, idx) => {
            const isFeature = idx === 0;
            return (
              <Link
                key={card.slug}
                href={`${prefix}/store/${card.slug}`}
                className={`border-border hover:border-primary/30 focus-visible:ring-primary group relative isolate overflow-hidden rounded-xl border transition hover:-translate-y-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset ${
                  isFeature ? "md:row-span-2" : "h-[240px] md:h-auto"
                }`}
              >
                {/* Real key-art */}
                <Image
                  src={card.bg}
                  alt=""
                  fill
                  sizes={
                    isFeature
                      ? "(max-width: 768px) 100vw, 400px"
                      : "(max-width: 768px) 100vw, 270px"
                  }
                  className="object-cover transition duration-500 group-hover:scale-[1.04]"
                />
                {/* Bottom shade for legibility */}
                <div className="absolute inset-0 bg-[linear-gradient(to_top,rgba(0,0,0,0.85)_0%,rgba(0,0,0,0.25)_50%,transparent_80%)]" />

                {/* Tag */}
                <span
                  className={`absolute left-4 top-4 z-10 inline-flex rounded-md px-2 py-1 text-[10px] font-black uppercase tracking-[0.06em] ${TAG_TONE[card.tagTone]}`}
                >
                  {t(`cards.${card.slug}.tag`)}
                </span>

                {/* Brand mark */}
                {card.icon && (
                  <span className="absolute right-4 top-4 z-10 flex h-11 w-11 items-center justify-center overflow-hidden rounded-[12px] border border-white/15 bg-black/40 backdrop-blur">
                    <Image
                      src={card.icon}
                      alt=""
                      width={28}
                      height={28}
                      className="h-7 w-7 object-contain"
                    />
                  </span>
                )}

                {/* Body */}
                <div className="absolute inset-x-5 bottom-5 z-10">
                  <div className="mb-1.5 text-[11px] font-bold uppercase tracking-[0.1em] text-white/65">
                    {t(`cards.${card.slug}.eyebrow`)}
                  </div>
                  <div className="flex items-end justify-between gap-3">
                    <div
                      className="font-display whitespace-pre-line font-extrabold leading-none tracking-[-0.025em] text-white"
                      style={{ fontSize: isFeature ? 54 : 26 }}
                    >
                      {t(`cards.${card.slug}.name`)}
                    </div>
                    {!isFeature && (
                      <div className="border-white/18 group-hover:bg-primary flex h-10 w-10 items-center justify-center rounded-[11px] border bg-black/45 backdrop-blur transition">
                        <ArrowRight
                          size={16}
                          className="group-hover:text-primary-foreground text-white transition"
                          strokeWidth={2.4}
                        />
                      </div>
                    )}
                  </div>
                  {isFeature && (
                    <p className="mt-3 max-w-[360px] text-[14px] leading-snug text-white/75">
                      {t("steamDesc")}
                    </p>
                  )}
                  {isFeature && (
                    <div className="mt-5 flex items-center justify-between">
                      <div className="flex gap-6">
                        {FEATURE_STATS.map((s) => (
                          <div key={s.labelKey}>
                            <div className="font-mono text-[9px] font-semibold uppercase tracking-[0.1em] text-white/55">
                              {t(s.labelKey)}
                            </div>
                            <div
                              className={`font-display text-base font-bold ${s.lime ? "text-primary" : "text-white"}`}
                            >
                              {t(s.valueKey)}
                            </div>
                          </div>
                        ))}
                      </div>
                      <div className="bg-primary flex h-[52px] w-[52px] items-center justify-center rounded-[14px] shadow-[0_10px_24px_-6px_hsl(var(--primary)/0.5)]">
                        <ArrowRight
                          size={22}
                          className="text-primary-foreground"
                          strokeWidth={2.6}
                        />
                      </div>
                    </div>
                  )}
                </div>
              </Link>
            );
          })}
        </div>
      </div>
    </section>
  );
}
