/**
 * Home hero carousel — informative, tappable slides at the top of the storefront.
 *
 * Slide artwork: 3D renders exported as ~1200×500 JPEG (~80 KB each), stored in
 * ``src/assets/hero/``. The gradient under each slide stays as a tinted fallback
 * (visible behind any image transparency and during the crossfade).
 */

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "wouter";

import instantImg from "@/assets/hero/instant.jpg";
import payImg from "@/assets/hero/pay.jpg";
import walletImg from "@/assets/hero/wallet.jpg";
import { useT, type MessageKey } from "@/lib/i18n";

interface HeroSlide {
  id: string;
  titleKey: MessageKey;
  subtitleKey: MessageKey;
  /** Deep link opened on tap. Omit for a purely informational slide. */
  href?: string;
  /** Pre-rendered 3D image (WebP). Falls back to ``gradient`` when absent. */
  image?: string;
  /** Placeholder background while the 3D render is pending. */
  gradient: string;
}

const SLIDES: HeroSlide[] = [
  {
    id: "instant",
    titleKey: "hero.instant.title",
    subtitleKey: "hero.instant.subtitle",
    image: instantImg,
    gradient: "linear-gradient(135deg, #0b2a6b 0%, #0ea5e9 100%)",
  },
  {
    id: "wallet",
    titleKey: "hero.wallet.title",
    subtitleKey: "hero.wallet.subtitle",
    href: "/wallet",
    image: walletImg,
    gradient: "linear-gradient(135deg, #064e3b 0%, #10b981 100%)",
  },
  {
    id: "pay",
    titleKey: "hero.pay.title",
    subtitleKey: "hero.pay.subtitle",
    image: payImg,
    gradient: "linear-gradient(135deg, #3b0a63 0%, #7c3aed 100%)",
  },
];

const ROTATE_MS = 5000;
const SWIPE_THRESHOLD = 40;

export function HeroCarousel() {
  const [, setLocation] = useLocation();
  const { t } = useT();
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const draggedRef = useRef(false);
  const count = SLIDES.length;

  useEffect(() => {
    if (paused || count <= 1) return;
    const t = setInterval(() => {
      setIndex((i) => (i + 1) % count);
    }, ROTATE_MS);
    return () => {
      clearInterval(t);
    };
  }, [paused, count]);

  const go = (i: number) => {
    setIndex(((i % count) + count) % count);
  };
  const active = SLIDES[index] ?? SLIDES[0];
  if (!active) return null;

  return (
    <div className="mx-4">
      <div className="relative h-[150px] w-full overflow-hidden rounded-3xl bg-black/20">
        <AnimatePresence initial={false}>
          <motion.div
            key={active.id}
            initial={{ opacity: 0, scale: 1.03 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.45 }}
            className="absolute inset-0"
            style={{ background: active.gradient }}
          >
            {active.image ? (
              <img
                src={active.image}
                alt=""
                className="absolute inset-0 h-full w-full object-cover"
              />
            ) : (
              <span className="absolute right-3 top-3 rounded-full bg-white/15 px-2 py-0.5 text-[9px] font-bold uppercase tracking-wider text-white/70">
                {t("hero.soon3d")}
              </span>
            )}
            <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/20 to-transparent" />
            <div className="absolute bottom-0 left-0 right-0 p-4">
              <p className="text-lg font-bold leading-tight text-white">{t(active.titleKey)}</p>
              <p className="mt-0.5 text-xs text-white/75">{t(active.subtitleKey)}</p>
            </div>
          </motion.div>
        </AnimatePresence>

        {/* Gesture + tap layer (above visuals, below dots). */}
        <motion.div
          className="absolute inset-0"
          style={{ cursor: active.href ? "pointer" : "default" }}
          drag="x"
          dragConstraints={{ left: 0, right: 0 }}
          dragElastic={0.15}
          role={active.href ? "link" : undefined}
          aria-label={active.href ? t(active.titleKey) : undefined}
          onPointerDown={() => {
            setPaused(true);
          }}
          onDragEnd={(_, info) => {
            if (info.offset.x < -SWIPE_THRESHOLD) {
              draggedRef.current = true;
              go(index + 1);
            } else if (info.offset.x > SWIPE_THRESHOLD) {
              draggedRef.current = true;
              go(index - 1);
            }
            setPaused(false);
          }}
          onClick={() => {
            if (draggedRef.current) {
              draggedRef.current = false;
              return; // a swipe, not a tap
            }
            if (active.href) setLocation(active.href);
          }}
        />

        {count > 1 && (
          <div className="absolute bottom-3 right-4 flex gap-1.5">
            {SLIDES.map((s, i) => (
              <button
                key={s.id}
                type="button"
                aria-label={t("hero.slide", { n: i + 1 })}
                onClick={(e) => {
                  e.stopPropagation();
                  setPaused(true);
                  go(i);
                }}
                className="h-1.5 rounded-full transition-all"
                style={{
                  width: i === index ? 16 : 6,
                  background: i === index ? "#fff" : "rgba(255,255,255,0.45)",
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
