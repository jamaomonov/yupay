/**
 * Two-tile promo row on Home: CS2 skin market + Steam top-up.
 *
 * Artwork sits bottom-right over a soft lime wash; copy is top-left.
 * Keep the glow subtle — just a hint of primary light behind the art.
 */

import { motion } from "framer-motion";
import { Link } from "wouter";

import sellSkinsImg from "@/assets/home/sellskins.webp";
import steamImg from "@/assets/home/steam.png";
import { useT, type MessageKey } from "@/lib/i18n";

interface PromoCard {
  href: string;
  titleKey: MessageKey;
  subtitleKey: MessageKey;
  image: string;
  imageAltKey: MessageKey;
  testId: string;
  imageClassName: string;
}

const CARDS: PromoCard[] = [
  {
    href: "/topup/steam",
    titleKey: "home.promo.steam.title",
    subtitleKey: "home.promo.steam.subtitle",
    image: steamImg,
    imageAltKey: "home.promo.steam.alt",
    testId: "promo-steam",
    imageClassName: "-bottom-2 -right-2 h-[112px] max-w-none w-[108%]",
  },
  {
    href: "/cs2-market",
    titleKey: "home.promo.skins.title",
    subtitleKey: "home.promo.skins.subtitle",
    image: sellSkinsImg,
    imageAltKey: "home.promo.skins.alt",
    testId: "promo-skins",
    imageClassName: "-bottom-4 -right-5 h-[142px] max-w-none w-[145%]",
  },
];

export function HomePromoCards() {
  const { t } = useT();

  return (
    <div className="grid grid-cols-2 gap-2.5 px-4">
      {CARDS.map((card, i) => (
        <Link key={card.href} href={card.href} data-testid={card.testId}>
          <motion.div
            whileTap={{ scale: 0.97 }}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.05, type: "spring", stiffness: 320, damping: 28 }}
            className="relative flex h-[152px] flex-col overflow-hidden rounded-2xl border p-3"
            style={{
              background:
                "radial-gradient(120% 90% at 85% 100%, hsl(var(--primary) / 0.28) 0%, hsl(var(--primary) / 0.08) 40%, hsl(var(--surface-1)) 74%)",
              // Keep the lime wash inside the padding box so it can't bleed
              // through the translucent border — the border then only reveals
              // the dark page bg, giving an even, soft edge.
              backgroundClip: "padding-box",
              borderColor: "hsl(var(--border) / 0.45)",
              boxShadow: "inset 0 1px 0 hsl(0 0% 100% / 0.04)",
            }}
          >
            <div
              aria-hidden
              className="pointer-events-none absolute -bottom-6 -right-5 h-28 w-28 rounded-full blur-2xl"
              style={{ background: "hsl(var(--primary) / 0.34)" }}
            />

            <div className="relative z-10 min-w-0 max-w-[76%] pr-0.5">
              <p className="text-[12px] font-bold leading-snug tracking-tight text-white">
                {t(card.titleKey)}
              </p>
              <p className="text-body-muted mt-0.5 text-[9.5px] leading-snug">{t(card.subtitleKey)}</p>
            </div>

            <img
              src={card.image}
              alt={t(card.imageAltKey)}
              draggable={false}
              className={`pointer-events-none absolute z-[1] select-none object-contain object-right-bottom drop-shadow-[0_6px_14px_rgba(0,0,0,0.45)] ${card.imageClassName}`}
            />
          </motion.div>
        </Link>
      ))}
    </div>
  );
}
